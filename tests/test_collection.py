import unittest

from indigo.models import Collection
from indigo.models.errors import UniqueException

from nose.tools import raises

class NodeTest(unittest.TestCase):

    def test_a_create_root(self):
        Collection.create(name="test_root", parent=None, path="/")
        coll = Collection.find("test_root")
        assert coll.name == "test_root"
        assert coll.path == '/'
        assert coll.parent is None

        # Make sure this is the root collection
        root = Collection.get_root_collection()
        assert root.id == coll.id

    def test_create_with_children(self):
        coll = Collection.find("test_root")
        assert coll.name == "test_root"
        assert coll.is_root

        child1 = Collection.create(name="child1", parent=str(coll.id))
        child2 = Collection.create(name="child2", parent=str(coll.id))

        assert child1.get_parent_collection().id == coll.id
        assert child2.get_parent_collection().id == coll.id

        assert child1.path == '/child1/'
        assert child2.path == '/child2/'

        children = coll.get_child_collections()
        assert len(children) == 2

        assert coll.get_child_collection_count() == 2
