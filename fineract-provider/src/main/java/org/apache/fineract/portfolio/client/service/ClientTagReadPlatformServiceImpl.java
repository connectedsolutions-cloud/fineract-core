/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
package org.apache.fineract.portfolio.client.service;

import java.util.List;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.exception.ResourceNotFoundException;
import org.apache.fineract.portfolio.client.data.ClientTagData;
import org.apache.fineract.portfolio.client.domain.ClientTag;
import org.apache.fineract.portfolio.client.domain.ClientTagRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ClientTagReadPlatformServiceImpl implements ClientTagReadPlatformService {

    private final ClientTagRepository clientTagRepository;

    @Override
    public List<ClientTagData> retrieveAllActiveTags() {
        final List<ClientTag> tags = clientTagRepository.findAllByIsActiveTrue();
        return tags.stream().map(ClientTagData::from).collect(Collectors.toList());
    }

    @Override
    public List<ClientTagData> retrieveTagsByGroup(final String group) {
        final List<ClientTag> tags = clientTagRepository.findByTagGroupAndIsActiveTrue(group);
        return tags.stream().map(ClientTagData::from).collect(Collectors.toList());
    }

    @Override
    public ClientTagData retrieveTag(final Long tagId) {
        final ClientTag tag = clientTagRepository.findById(tagId)
                .orElseThrow(() -> new ResourceNotFoundException("error.msg.client.tag.not.found", "Client tag not found with id: " + tagId, new Object[] { tagId }));
        return ClientTagData.from(tag);
    }
}
