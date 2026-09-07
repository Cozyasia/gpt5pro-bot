import unittest
import cv2
import numpy as np
from neyrobot_prod.v265_transfer_lab import full_face_support, interior_alpha


def fixture():
    p = np.tile([200.0, 200.0], (68, 1))
    t = np.linspace(0, np.pi, 17)
    p[:17] = np.c_[200 - 120 * np.cos(t), 160 + 170 * np.sin(t)]
    p[17:27] = np.c_[np.linspace(100, 300, 10), np.full(10, 140)]
    for j, x in [(36, 140), (42, 260)]:
        a = np.linspace(0, 2 * np.pi, 6, endpoint=False)
        p[j : j + 6] = np.c_[x + 20 * np.cos(a), 180 + 7 * np.sin(a)]
    a = np.linspace(0, 2 * np.pi, 20, endpoint=False)
    p[48:68] = np.c_[200 + 45 * np.cos(a), 270 + 15 * np.sin(a)]
    return p


class FullFaceMaskTests(unittest.TestCase):
    def test_jaw_chin_lower_lip_inside_neck_and_person_b_outside(self):
        p = fixture()
        for roll in (-25, 0, 25):
            m = cv2.getRotationMatrix2D((200, 200), roll, 1)
            q = p @ m[:, :2].T + m[:, 2]
            mask = full_face_support((500, 600, 3), q, 400)
            alpha = interior_alpha(mask, 300)
            for i in list(range(17)) + list(range(48, 68)):
                x, y = np.rint(q[i]).astype(int)
                self.assertGreater(mask[y, x], 0, (roll, i))
                self.assertGreater(alpha[y, x], 0, (roll, i))
            neck = np.array([200.0, 370.0]) @ m[:, :2].T + m[:, 2]
            x, y = np.rint(neck).astype(int)
            self.assertEqual(mask[y, x], 0)
            self.assertEqual(mask[:, 400:].max(), 0)
            self.assertEqual(alpha[mask == 0].max(), 0)
