from researchgit.versioning.diff import structural_diff
def test_added_modified_and_removed_paragraphs():
    changes=structural_diff("One is old.\n\nRemove me.","One is new.\n\nAdd me.")
    assert any(x["kind"]=="MODIFIED" for x in changes)
    assert any(x["kind"]=="REMOVED" for x in changes)
    assert any(x["kind"]=="ADDED" for x in changes)
