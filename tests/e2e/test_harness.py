"""Placeholder for the e2e package. This is NOT the demo test: see tests/e2e/__init__.py."""


def test_tests_in_this_package_are_auto_marked_e2e(request):
    assert request.node.get_closest_marker("e2e") is not None
