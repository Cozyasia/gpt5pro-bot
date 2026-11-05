import numpy as np

from neyrobot_prod.v265_l2_geometry import (
    expression_invariant_landmark_delta,
    projected_surface_validity,
    rotation_matrix,
    split_faceverse,
    triangle_distortion,
)


def test_faceverse_parameter_contract_is_explicit():
    p = split_faceverse(np.arange(621, dtype=np.float32))
    assert p["identity"].shape == (156,)
    assert p["expression"].shape == (177,)
    assert p["texture"].shape == (251,)
    assert p["angles"].shape == (3,)
    assert p["eyes"].shape == (4,)


def test_expression_invariant_residual_cannot_encode_aperture():
    observed = np.zeros((68, 2), np.float32)
    projected = np.zeros((68, 2), np.float32)
    observed[62, 1], observed[66, 1] = -4, 8
    delta = expression_invariant_landmark_delta(observed, projected)
    np.testing.assert_array_equal(delta[62], delta[66])


def test_rigid_pose_does_not_create_local_deformation():
    vertices = np.array([[0, 0, 1], [1, 0, 1], [0, 1, 1]], np.float32)
    triangles = np.array([[0, 1, 2]], np.int32)
    target = vertices @ rotation_matrix([.2, -.1, .3]) + [3, 4, 5]
    report = triangle_distortion(vertices, target, triangles)
    assert report["orientation_failures"] == 0
    assert abs(report["local_area_ratio"]["0.5"] - 1) < 1e-6
    assert abs(report["edge_stretch"]["0.5"] - 1) < 1e-6


def test_projected_surface_reports_connected_triangle():
    projected = np.array([[0, 0, 1], [10, 0, 1], [0, 10, 1]], np.float32)
    report = projected_surface_validity(projected, np.array([[0, 1, 2]], np.int32), 32)
    assert report["visible_projection_triangles"] == 1
    assert report["silhouette_components"] == 1
    assert report["silhouette_holes"] == 0


def test_invalid_parameter_length_fails_closed():
    try:
        split_faceverse(np.zeros(620, np.float32))
    except ValueError:
        pass
    else:
        raise AssertionError("invalid parameter vector accepted")
