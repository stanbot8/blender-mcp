"""Mock Blender collection types (bpy.data.objects, edit_bones, etc.)."""


class MockCollection:
    """Generic ordered dict-like collection mimicking Blender data collections."""

    def __init__(self, factory=None):
        self._items = {}      # name -> item
        self._order = []      # insertion order
        self._factory = factory  # callable(name, **kw) -> item

    def get(self, name, default=None):
        return self._items.get(name, default)

    def new(self, name=None, data=None, **kwargs):
        if self._factory:
            item = self._factory(name=name, data=data, **kwargs)
        else:
            raise NotImplementedError("No factory set for this collection")
        # Handle Blender-style name deduplication
        if name in self._items:
            i = 1
            while f"{name}.{i:03d}" in self._items:
                i += 1
            item.name = f"{name}.{i:03d}"
        self._items[item.name] = item
        self._order.append(item)
        return item

    def remove(self, item):
        name = item.name if hasattr(item, 'name') else item
        if name in self._items:
            obj = self._items.pop(name)
            self._order = [o for o in self._order if o.name != name]
            return obj
        raise ValueError(f"Item not found: {name}")

    def link(self, item):
        """For bpy.context.collection.objects.link()."""
        self._items[item.name] = item
        self._order.append(item)

    def __contains__(self, name):
        return name in self._items

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._order[key]
        return self._items[key]

    def __iter__(self):
        return iter(self._order)

    def __len__(self):
        return len(self._order)

    def __bool__(self):
        return True  # Collection always truthy (like bpy collections)

    def keys(self):
        return self._items.keys()

    def values(self):
        return self._order

    def items(self):
        return self._items.items()

    def clear(self):
        self._items.clear()
        self._order.clear()
