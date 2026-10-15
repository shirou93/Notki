import unittest
import qr

class TestQRGenerator(unittest.TestCase):

    def test_format_info(self):
        # Expected format info for EC Level M (00) and mask patterns 0-7
        expected_outputs = [
            0x5412, 0x5125, 0x5E7C, 0x5B4B,
            0x45F9, 0x40CE, 0x4F97, 0x4AA0
        ]
        for pattern, expected in enumerate(expected_outputs):
            with self.subTest(pattern=pattern):
                self.assertEqual(qr.get_format_info(pattern), expected)

    def test_version_info(self):
        # Version info for Version 7
        v_info = qr.get_version_info(7)
        self.assertEqual(v_info, 0x7C94)

    def test_qr_matrix_dimensions(self):
        # Short string -> Version 1 (21x21)
        m1 = qr.generate_qr_matrix("hello")
        self.assertEqual(len(m1), 21)
        self.assertEqual(len(m1[0]), 21)

        # Medium TOTP string -> Version 5 (37x37)
        totp = "otpauth://totp/Notki:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Notki"
        m5 = qr.generate_qr_matrix(totp)
        self.assertEqual(len(m5), 37)
        self.assertEqual(len(m5[0]), 37)

    def test_qr_matrix_finder_patterns(self):
        m = qr.generate_qr_matrix("test")
        # Top-left finder pattern center (2,2) should be black (1)
        self.assertEqual(m[2][2], 1)
        # Top-left finder pattern outer ring
        self.assertEqual(m[0][0], 1)
        self.assertEqual(m[0][6], 1)
        self.assertEqual(m[6][0], 1)
        self.assertEqual(m[6][6], 1)
        # Separator ring
        self.assertEqual(m[0][7], 0)
        self.assertEqual(m[7][0], 0)

    def test_qr_matrix_format_info_bits(self):
        m = qr.generate_qr_matrix("test")
        size = len(m)
        # Check dark module at (size-8, 8)
        self.assertEqual(m[size - 8][8], 1)
        # Check that top-left vertical format info MSB at (0, 8) and horizontal format info MSB at (8, 0) are set properly
        self.assertIn(m[0][8], (0, 1))
        self.assertEqual(m[0][8], m[8][0])  # Both vertical and horizontal start with bit 14 (MSB)

    def test_qr_svg_output(self):
        svg = qr.generate_qr_svg("hello", module_size=4, border=4)
        self.assertIn('<svg xmlns="http://www.w3.org/2000/svg"', svg)
        self.assertIn('viewBox="0 0 116 116"', svg)  # (21 + 8) * 4 = 116
        self.assertIn('<rect', svg)

    def test_qr_data_too_long(self):
        huge_text = "A" * 1000
        with self.assertRaises(qr.QRError):
            qr.generate_qr_matrix(huge_text)


if __name__ == "__main__":
    unittest.main()
