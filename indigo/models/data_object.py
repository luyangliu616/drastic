"""Resource Model

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

from cStringIO import StringIO
import zipfile
from datetime import datetime
from cassandra.cqlengine import (
    columns,
    connection
)
from cassandra.query import SimpleStatement
from cassandra.cqlengine.models import Model

from indigo import get_config
from indigo.models import (
    Group,
)
from indigo.models.acl import (
    Ace,
    cdmi_str_to_aceflag,
    str_to_acemask,
    cdmi_str_to_acemask,
)
from indigo.util import default_cdmi_id


static_fields = ["checksum",
                 "size",
                 "metadata",
                 "mimetype",
                 "alt_url",
                 "create_ts",
                 "modified_ts",
                 "type",
                 "acl",
                 "treepath"]


class DataObject(Model):
    """ The DataObject represents actual data objects, the tree structure
    merely references it.

    Each partition key gathers together all the data under one partition (the
    CDMI ID ) and the object properties are represented using static columns
    (one instance per partition)
    It has a similar effect to a join to a properties table, except the
    properties are stored with the rest of the partition

    This is an 'efficient' model optimised for Cassandra's quirks.

    N.B. by default Cassandra compresses its data ( using LZW ), so we get that
    for free."""
    # The 'name' of the object
    uuid = columns.Text(default=default_cdmi_id, required=True,
                        partition_key=True)
    #####################
    # These columns are the same (shared) between all entries with same id
    # (they use the static attribute , [ like an inode or a header ])
    #####################
    checksum = columns.Text(static=True)
    size = columns.BigInt(default=0, static=True)
    metadata = columns.Map(columns.Text, columns.Text, static=True)
    mimetype = columns.Text(static=True)
    alt_url = columns.Set(columns.Text, static=True)
    create_ts = columns.DateTime(default=datetime.now, static=True)
    modified_ts = columns.DateTime(default=datetime.now, static=True)
    type = columns.Text(required=False, static=True, default='UNKNOWN')
    acl = columns.Map(columns.Text, columns.UserDefinedType(Ace), static=True)
    # A general aid to integrity ...
    treepath = columns.Text(static=True, required=False)
    #####################
    # And 'clever' bit -- 'here' data, These will be the only per-record-fields
    # in the partition (i.e. object)
    # So the datastructure looks like a header , with an ordered list of blobs
    #####################
    # This is the 'clustering' key...
    sequence_number = columns.Integer(primary_key=True, partition_key=False)
    blob = columns.Blob(required=False)
    compressed = columns.Boolean(default=False)
    #####################

    @classmethod
    def append_chunk(cls, uuid, data, sequence_number, compressed=False):
        """Create a new blob for an existing data_object"""
        data_object = cls(uuid=uuid,
                          sequence_number=sequence_number,
                          blob=data,
                          compressed=compressed)
        data_object.save()
        return data_object


    def chunk_content(self):
        """
        Yields the content for the driver's URL, if any
        a chunk at a time.  The value yielded is the size of
        the chunk and the content chunk itself.
        """
        entries = DataObject.objects.filter(uuid=self.uuid)
        for entry in entries:
            if entry.compressed:
                data = StringIO(entry.blob)
                z = zipfile.ZipFile(data, 'r')
                content = z.read("data")
                data.close()
                z.close()
                yield content
            else:
                yield entry.blob


    @classmethod
    def create(cls, data, compressed=False):
        """data: initial data"""
        new_id = default_cdmi_id()
        now = datetime.now()
        kwargs = {
            "uuid": new_id,
            "sequence_number": 0,
            "blob": data,
            "compressed": compressed,
            "create_ts": now,
            "modified_ts": now
        }
        new = super(DataObject, cls).create(**kwargs)
        return new


    def create_acl(self, read_access, write_access):
        """Create ACL from two lists of groups id, existing ACL are replaced"""
        self.update_acl(read_access, write_access)


    @classmethod
    def delete_id(cls, uuid):
        """Delete all blobs for the specified uuid"""
        cfg = get_config(None)
        session = connection.get_session()
        keyspace = cfg.get('KEYSPACE', 'indigo')
        session.set_keyspace(keyspace)
        query = SimpleStatement("""DELETE FROM data_object WHERE uuid=%s""")
        session.execute(query, (uuid,))


    @classmethod
    def find(cls, uuid):
        """Find an object by uuid"""
        entries = cls.objects.filter(uuid=uuid)
        if not entries:
            return None
        else:
            return entries.first()


    def update(self, **kwargs):
        """Update a data object"""
        cfg = get_config(None)
        session = connection.get_session()
        keyspace = cfg.get('KEYSPACE', 'indigo')
        session.set_keyspace(keyspace)

#         if "mimetype" in kwargs:
#             metadata = kwargs.get('metadata', {})
#             metadata["cdmi_mimetype"] = kwargs["mimetype"]
#             kwargs['metadata'] = meta_cdmi_to_cassandra(metadata)
#             del kwargs['mimetype']

        for arg in kwargs:
            # For static fields we can't use the name in the where condition
            if arg in static_fields:
                query = SimpleStatement("""UPDATE data_object SET {}=%s
                    WHERE uuid=%s""".format(arg))
                session.execute(query, (kwargs[arg], self.uuid))
            else:
                query = SimpleStatement("""UPDATE data_object SET {}=%s
                    WHERE uuid=%s and sequence_number=%s""".format(arg))
                session.execute(query, (kwargs[arg], self.container, self.sequence_number))
        return self


    def update_acl(self, read_access, write_access):
        """Replace the acl with the given list of access.

        read_access: a list of groups id that have read access for this
                     collection
        write_access: a list of groups id that have write access for this
                     collection

        """
        cfg = get_config(None)
        keyspace = cfg.get('KEYSPACE', 'indigo')
        # The ACL we construct will replace the existing one
        # The dictionary keys are the groups id for which we have an ACE
        # We don't use aceflags yet, everything will be inherited by lower
        # sub-collections
        # acemask is set with helper (read/write - see indigo/models/acl/py)
        access = {}
        for gid in read_access:
            access[gid] = "read"
        for gid in write_access:
            if gid in access:
                access[gid] = "read/write"
            else:
                access[gid] = "write"
        ls_access = []
        for gid in access:
            group = Group.find_by_uuid(gid)
            if group:
                ident = group.name
            elif gid.upper() == "AUTHENTICATED@":
                ident = "AUTHENTICATED@"
            else:
                # TODO log or return error if the identifier isn't found ?
                continue
            s = ("'{}': {{"
                 "acetype: 'ALLOW', "
                 "identifier: '{}', "
                 "aceflags: {}, "
                 "acemask: {}"
                 "}}").format(gid, ident, 0, str_to_acemask(access[gid], True))
            ls_access.append(s)
        acl = "{{{}}}".format(", ".join(ls_access))
        query = ("UPDATE {}.data_object SET acl = acl + {}"
                 "WHERE uuid='{}'").format(
            keyspace,
            acl,
            self.uuid)
        connection.execute(query)


    def update_cdmi_acl(self, cdmi_acl):
        """Update acl with the metadata acl passed with a CDMI request"""
        cfg = get_config(None)
        session = connection.get_session()
        keyspace = cfg.get('KEYSPACE', 'indigo')
        session.set_keyspace(keyspace)
        ls_access = []
        for cdmi_ace in cdmi_acl:
            if 'identifier' in cdmi_ace:
                gid = cdmi_ace['identifier']
            else:
                # Wrong syntax for the ace
                continue
            group = Group.find(gid)
            if group:
                ident = group.name
            elif gid.upper() == "AUTHENTICATED@":
                ident = "AUTHENTICATED@"
            else:
                # TODO log or return error if the identifier isn't found ?
                continue
            s = ("'{}': {{"
                 "acetype: '{}', "
                 "identifier: '{}', "
                 "aceflags: {}, "
                 "acemask: {}"
                 "}}").format(group.uuid,
                              cdmi_ace['acetype'].upper(),
                              ident,
                              cdmi_str_to_aceflag(cdmi_ace['aceflags']),
                              cdmi_str_to_acemask(cdmi_ace['acemask'], False)
                             )
            ls_access.append(s)
        acl = "{{{}}}".format(", ".join(ls_access))
        query = """UPDATE data_object SET acl={}
            WHERE uuid='{}'""".format(acl, self.uuid)
        session.execute(query)
