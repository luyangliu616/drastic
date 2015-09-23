"""Node Model

Copyright 2015 Archive Analytics Solutions

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import uuid
from datetime import datetime
from cassandra.cqlengine import columns
from cassandra.cqlengine.models import Model

from indigo.models.errors import NodeConflictError
from indigo.util import default_uuid


class Node(Model):
    """Node Model"""
    id = columns.Text(primary_key=True, default=default_uuid)
    name = columns.Text(required=True, index=True)
    address = columns.Text(required=True, index=True)
    last_update = columns.DateTime()
    status = columns.Text(required=True, default="UP")

    @classmethod
    def create(cls, **kwargs):
        """Create a node
        We intercept the create call so that we can check for uniqueness
        of IP
        """
        if cls.objects.filter(address=kwargs['address']).count():
            raise NodeConflictError(kwargs['address'])
        if not kwargs.get("last_update"):
            kwargs["last_update"] = datetime.now()
        kwargs["id"] = unicode(uuid.uuid4())
        return super(Node, cls).create(**kwargs)

    @classmethod
    def find(cls, name_or_address):
        """Find a node by its name or its address"""
        node = cls.objects.filter(name=name_or_address).first()
        if not node:
            node = cls.objects.filter(address=name_or_address).first()
        return node

    @classmethod
    def find_by_id(cls, idstring):
        """Find a node by its id"""
        return cls.objects.filter(id=idstring).first()

    @classmethod
    def list(cls):
        """List all nodes"""
        return cls.objects.all()

    def __unicode__(self):
        return "{}/{}".format(self.name, self.address)

    def status_up(self):
        """Change the status of the node"""
        self.update(status="UP")

    def status_down(self):
        """Change the status of the node"""
        self.update(status="DOWN")

    def to_dict(self):
        """Return a dictionary that represents the node"""
        return {
            'id': self.id,
            'name': self.name,
            'address': self.address,
            'last_update': self.last_update,
            'status': self.status
        }
