#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at
# 
# http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.
"""Synthetic refinance origination/undo check for an already prepared disposable local clone.

No cloning, resets, migrations or direct SQL writes. Requires requests and psycopg.
Credentials: FINERACT_TEST_USER, FINERACT_TEST_PASSWORD, REFINANCE_TEST_PG_DSN.
"""
import argparse
import datetime as dt
import json
import os
from decimal import Decimal
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--tenant', default='default')
    parser.add_argument('--product-id', required=True, type=int)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    url = urlparse(args.base_url)
    if url.hostname not in ('127.0.0.1', 'localhost') or url.port != 9443 or url.scheme != 'https':
        parser.error('Only the isolated HTTPS local test instance on port 9443 is allowed')
    with psycopg.connect(os.environ['REFINANCE_TEST_PG_DSN'], row_factory=dict_row) as db:
        db.read_only = True
        database = db.execute('SELECT current_database() AS name').fetchone()['name']
        if not database.startswith('refinance_test_data_'):
            parser.error('Database must be a disposable refinance_test_data_* clone')
        session = requests.Session()
        session.auth = (os.environ['FINERACT_TEST_USER'], os.environ['FINERACT_TEST_PASSWORD'])
        session.headers['Fineract-Platform-TenantId'] = args.tenant
        # This isolated development instance uses its local self-signed certificate.
        session.verify = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        def api(path, data=None):
            response = session.request('GET' if data is None else 'POST', args.base_url.rstrip('/') + '/' + path,
                                       json=data, timeout=90)
            response.raise_for_status()
            return response.json()

        dates = api('businessdate')
        today = dt.datetime.now(ZoneInfo('America/El_Salvador')).date()
        for item in dates:
            if item.get('type') == 'BUSINESS_DATE':
                value = item['date']
                today = dt.date(*value) if isinstance(value, list) else dt.date.fromisoformat(value)
        previous = today - dt.timedelta(days=1)
        locale = {'locale': 'en', 'dateFormat': 'yyyy-MM-dd'}
        tag = 'REFINANCE-ACCEPTANCE-' + uuid4().hex[:12]
        client = api('clients', {'officeId': 1, 'legalFormId': 1, 'firstname': 'Synthetic', 'lastname': tag,
                                'externalId': tag, 'active': True, 'activationDate': previous.isoformat(), **locale})['clientId']

        def loan(role, principal, date, predecessor=None):
            body = {'clientId': client, 'productId': args.product_id, 'principal': principal,
                    'loanTermFrequency': 12, 'loanTermFrequencyType': 2, 'numberOfRepayments': 12,
                    'repaymentEvery': 1, 'repaymentFrequencyType': 2, 'interestRatePerPeriod': 1,
                    'interestType': 0, 'interestCalculationPeriodType': 0, 'amortizationType': 1,
                    'transactionProcessingStrategyCode': 'credesal-accrued-interest-first-strategy',
                    'expectedDisbursementDate': date.isoformat(), 'submittedOnDate': date.isoformat(),
                    'loanType': 'individual', 'charges': [], 'externalId': tag + ':' + role, **locale}
            if predecessor:
                body.update(isTopup=True, loanIdToClose=predecessor)
            identifier = api('loans', body)['loanId']
            api(f'loans/{identifier}?command=approve', {'approvedOnDate': date.isoformat(),
                'approvedLoanAmount': principal, **locale})
            return identifier

        report = {'database': database, 'tenant': args.tenant, 'tag': tag, 'cases': {}}
        for retained in (False, True):
            name = 'retained' if retained else 'standard-payout'
            old = loan(name + ':old', 4000, previous)
            api(f'loans/{old}?command=disburse', {'actualDisbursementDate': previous.isoformat(),
                'transactionAmount': 4000, **locale})
            new = loan(name + ':new', 6000, today, old)
            payload = {'actualDisbursementDate': today.isoformat(), 'transactionAmount': 6000, **locale}
            if retained:
                payload['applyRefinancingSurplusAsRepayment'] = True
            api(f'loans/{new}?command=disburse', payload)
            operation = api(f'loans/{new}/refinancing')
            assert operation['canReverse'] and operation['proceedsMode'] == ('RETAINED' if retained else 'CASH')
            entries = db.execute("""SELECT j.id, j.amount, j.type_enum, a.gl_code
                FROM m_loan_refinancing_operation_journal link
                JOIN acc_gl_journal_entry j ON j.id=link.journal_entry_id
                JOIN acc_gl_account a ON a.id=j.account_id WHERE link.operation_id=%s""",
                (operation['operationId'],)).fetchall()
            assert sum(e['amount'] if e['type_enum'] == 2 else -e['amount'] for e in entries) == 0
            assert not any(e['gl_code'].startswith('111001') or e['gl_code'] == '14' for e in entries)
            assert Decimal(str(operation['payoutEntitlement'])) == (Decimal(0) if retained else Decimal('1735.22'))
            undo = {'transactionDate': today.isoformat(), 'note': 'Synthetic acceptance unwind', **locale}
            api(f'loans/{new}?command=undodisbursal', undo)
            assert api(f'loans/{old}')['status']['active']
            assert api(f'loans/{new}')['status']['waitingForDisbursal']
            assert api(f'loans/{new}?command=undodisbursal', undo)['changes']['alreadyReversed']
            report['cases'][name] = {'oldLoanId': old, 'newLoanId': new, 'operationId': operation['operationId'],
                                    'balanced': True, 'noCashTurnover': True, 'undoAndRepeatPassed': True}
        with open(args.output, 'w', encoding='utf-8') as out:
            json.dump(report, out, indent=2)
        print('Both native payout and retained-payment origination/undo checks passed on', database)


if __name__ == '__main__':
    main()
