"""The picture reader: Doom's format, and the boundary it must not cross.

These build a WAD in memory rather than reading one off disk, so the suite still runs on a machine with
no game installed -- which is the same reason tests/test_grader.py builds one.
"""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "payload"))

import textures as tx                                          # noqa: E402


def patch(width, height, columns):
    """A Doom picture. `columns` is one list of (top_row, [palette indices]) per column."""
    head = struct.pack("<HHhh", width, height, 0, 0)
    offsets_at = len(head)
    body, offs = b"", []
    base = offsets_at + 4 * width
    for posts in columns:
        offs.append(base + len(body))
        for top, pixels in posts:
            body += bytes([top, len(pixels)]) + b"\0" + bytes(pixels) + b"\0"
        body += b"\xff"
    return head + struct.pack("<%dI" % width, *offs) + body


def wad(lumps):
    """An IWAD with the given (name, bytes) lumps, in order."""
    head = b"IWAD" + struct.pack("<ii", len(lumps), 0)
    body, dirents, at = b"", [], len(head)
    for name, raw in lumps:
        dirents.append((at + 0, len(raw), name))
        body += raw
        at += len(raw)
    dir_off = len(head) + len(body)
    out = b"IWAD" + struct.pack("<ii", len(lumps), dir_off) + body
    for pos, size, name in dirents:
        out += struct.pack("<ii8s", pos, size, name.encode().ljust(8, b"\0"))
    return out


class TestTheFormat(unittest.TestCase):
    def test_a_post_leaves_everything_it_did_not_cover_transparent(self):
        raw = patch(2, 4, [[(1, [10, 11])], [(0, [20])]])
        rows, w, h = tx.read_patch(raw)
        self.assertEqual((w, h), (2, 4))
        self.assertEqual(rows[0], [tx.TRANSPARENT, 20])
        self.assertEqual(rows[1], [10, tx.TRANSPARENT])
        self.assertEqual(rows[2], [11, tx.TRANSPARENT])
        self.assertEqual(rows[3], [tx.TRANSPARENT, tx.TRANSPARENT])

    def test_a_truncated_picture_is_refused_rather_than_guessed_at(self):
        rows, _w, _h = tx.read_patch(b"\x04\x00\x04\x00\x00\x00\x00\x00")
        self.assertIsNone(rows, "a header with no column offsets is not a picture")


class TestWhatAPlayerBrings(unittest.TestCase):
    def setUp(self):
        pal = bytes(bytearray([(i * 7) % 256 for i in range(256 * 3)]))
        pnames = struct.pack("<i", 1) + b"WSWITCH\0"
        pic = patch(4, 4, [[(0, [1, 2, 3, 4])]] * 4)
        tex1 = self._texture_lump([("SW1TEST", 4, 4, [(0, 0, 0)]),
                                   ("EXITSIGN", 4, 4, [(0, 0, 0)]),
                                   ("BROWN1", 4, 4, [(0, 0, 0)])])
        self.path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tx_test.wad")
        open(self.path, "wb").write(wad([("PLAYPAL", pal), ("PNAMES", pnames),
                                         ("TEXTURE1", tex1), ("WSWITCH", pic)]))

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    @staticmethod
    def _texture_lump(entries):
        head = struct.pack("<i", len(entries))
        recs, offs, base = b"", [], 4 + 4 * len(entries)
        for name, w, h, patches in entries:
            offs.append(base + len(recs))
            recs += name.encode().ljust(8, b"\0") + struct.pack("<iHHiH", 0, w, h, 0, len(patches))
            for pidx, px, py in patches:
                recs += struct.pack("<hhHHH", px, py, pidx, 0, 0)
        return head + struct.pack("<%di" % len(entries), *offs) + recs

    def test_it_finds_the_switches_and_the_exit_sign_and_not_the_wall(self):
        t = tx.Textures(self.path)
        names = [n for n, _rgb, _mask in t.switches()]
        self.assertIn("SW1TEST", names)
        self.assertNotIn("BROWN1", names, "a wall is not a switch")
        self.assertEqual(len(t.exit_signs()), 1)

    def test_a_composed_texture_carries_its_opacity(self):
        got = tx.Textures(self.path).named("SW1TEST")
        self.assertIsNotNone(got)
        rgb, solid = got
        self.assertEqual(rgb.shape, (4, 4, 3))
        self.assertTrue(solid.any(), "nothing was drawn at all")


class TestTheBoundary(unittest.TestCase):
    def test_the_reader_knows_nothing_about_levels(self):
        """Map lumps stay forbidden: this module must not name one, even to skip it."""
        src = open(os.path.join(ROOT, "payload", "textures.py"), encoding="utf-8").read()
        for lump in ('"LINEDEFS"', '"SECTORS"', '"THINGS"', '"VERTEXES"', '"SIDEDEFS"'):
            self.assertNotIn(lump, src, "textures.py reads %s" % lump)


if __name__ == "__main__":
    unittest.main()
