from django.urls import resolve, reverse


def test_metagraph_explorer_is_exposed_through_admin_site():
    url = reverse("admin:metagraph_explorer")

    assert url == "/admin/metagraph/explorer/"
    assert resolve(url).view_name == "admin:metagraph_explorer"
