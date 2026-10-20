import unittest

from arissto_sync.share_certificate_sequences import counter_seed


class ShareCertificateSequenceTests(unittest.TestCase):

    def test_seeds_last_issued_provisional_certificate_and_share_serials(self):
        counters = counter_seed([
            {"NUMERO_CERTIFICADO": "CP00000143", "ACCION_FIN": "10", "ID_TIPO_ACCION": 1},
            {"NUMERO_CERTIFICADO": "006581AC04", "ACCION_FIN": "40", "ID_TIPO_ACCION": 1},
            {"NUMERO_CERTIFICADO": "006581AP02", "ACCION_FIN": "20", "ID_TIPO_ACCION": 2},
            {"NUMERO_CERTIFICADO": "025981C101", "ACCION_FIN": "5", "ID_TIPO_ACCION": 1},
            {"certificate_number": "006581AC09", "share_serial_end": 15, "share_class_code": "1AC"},
        ])

        self.assertEqual(counters["SHARE_CERTIFICATE_PROVISIONAL|CP"], 143)
        self.assertEqual(counters["SHARE_CERTIFICATE|006581AC"], 9)
        self.assertEqual(counters["SHARE_CERTIFICATE|006581AP"], 2)
        self.assertEqual(counters["SHARE_SERIAL|COMMON"], 40)
        self.assertEqual(counters["SHARE_SERIAL|PREFERRED"], 20)
        self.assertNotIn("SHARE_CERTIFICATE|025981C101", counters)
