"""Pure-Python mock of Blender's mathutils module."""

import math


class Vector:
    """Minimal Vector that supports the operations used in addon.py."""

    __slots__ = ('_data',)

    def __init__(self, data=(0.0, 0.0, 0.0)):
        if isinstance(data, Vector):
            self._data = list(data._data)
        else:
            self._data = [float(v) for v in data]

    # --- properties ---
    @property
    def x(self):
        return self._data[0]

    @x.setter
    def x(self, v):
        self._data[0] = float(v)

    @property
    def y(self):
        return self._data[1]

    @y.setter
    def y(self, v):
        self._data[1] = float(v)

    @property
    def z(self):
        return self._data[2]

    @z.setter
    def z(self, v):
        self._data[2] = float(v)

    @property
    def length(self):
        return math.sqrt(sum(v * v for v in self._data))

    # --- sequence protocol ---
    def __len__(self):
        return len(self._data)

    def __getitem__(self, idx):
        return self._data[idx]

    def __setitem__(self, idx, val):
        self._data[idx] = float(val)

    def __iter__(self):
        return iter(self._data)

    # --- arithmetic ---
    def __add__(self, other):
        if isinstance(other, Vector):
            return Vector([a + b for a, b in zip(self._data, other._data)])
        return NotImplemented

    def __sub__(self, other):
        if isinstance(other, Vector):
            return Vector([a - b for a, b in zip(self._data, other._data)])
        return NotImplemented

    def __mul__(self, scalar):
        return Vector([v * scalar for v in self._data])

    def __rmul__(self, scalar):
        return self.__mul__(scalar)

    def __neg__(self):
        return Vector([-v for v in self._data])

    def __eq__(self, other):
        if isinstance(other, Vector):
            return all(abs(a - b) < 1e-7 for a, b in zip(self._data, other._data))
        if isinstance(other, (list, tuple)):
            return all(abs(a - b) < 1e-7 for a, b in zip(self._data, other))
        return NotImplemented

    def __repr__(self):
        return f"Vector({self._data})"

    # --- methods ---
    def copy(self):
        return Vector(self._data)

    def normalized(self):
        ln = self.length
        if ln < 1e-10:
            return Vector([0.0] * len(self._data))
        return Vector([v / ln for v in self._data])

    def dot(self, other):
        return sum(a * b for a, b in zip(self._data, other._data))

    def cross(self, other):
        a, b = self._data, other._data
        return Vector([
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ])

    # Matrix @ Vector support (matrix calls __matmul__ on its side)
    def __matmul__(self, other):
        return NotImplemented


class Matrix:
    """4x4 identity-like matrix. Supports @ Vector."""

    def __init__(self, rows=None):
        if rows:
            self._rows = [list(r) for r in rows]
        else:
            self._rows = [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]

    def __matmul__(self, other):
        if isinstance(other, Vector):
            # Treat 3D vector as (x, y, z, 1), return 3D vector
            v = list(other._data) + [1.0] if len(other._data) == 3 else list(other._data)
            result = []
            for row in self._rows[:3]:
                result.append(sum(a * b for a, b in zip(row, v)))
            return Vector(result)
        return NotImplemented

    @staticmethod
    def Identity(size):
        m = Matrix()
        return m


class Euler:
    """Minimal Euler angles."""

    __slots__ = ('_data', 'order')

    def __init__(self, data=(0.0, 0.0, 0.0), order='XYZ'):
        if isinstance(data, Euler):
            self._data = list(data._data)
        else:
            self._data = [float(v) for v in data]
        self.order = order

    @property
    def x(self):
        return self._data[0]

    @property
    def y(self):
        return self._data[1]

    @property
    def z(self):
        return self._data[2]

    def __iter__(self):
        return iter(self._data)

    def __repr__(self):
        return f"Euler({self._data})"


class Quaternion:
    """Minimal Quaternion."""

    __slots__ = ('_data',)

    def __init__(self, data=(1.0, 0.0, 0.0, 0.0)):
        if isinstance(data, Quaternion):
            self._data = list(data._data)
        else:
            self._data = [float(v) for v in data]

    @property
    def w(self):
        return self._data[0]

    @property
    def x(self):
        return self._data[1]

    @property
    def y(self):
        return self._data[2]

    @property
    def z(self):
        return self._data[3]

    def __iter__(self):
        return iter(self._data)

    def __repr__(self):
        return f"Quaternion({self._data})"
