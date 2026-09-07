from bot.telegram.images import parse_images


def test_parse_images_no_placeholders():
    clean, ids = parse_images("Hello world")
    assert clean == "Hello world"
    assert ids == []


def test_parse_images_single_placeholder():
    clean, ids = parse_images("Here is a photo: [[img:f4ec367b03bf]] of the Eiffel tower")
    assert clean == "Here is a photo:  of the Eiffel tower"
    assert ids == ["f4ec367b03bf"]


def test_parse_images_multiple_placeholders():
    text = "First [[img:aaa]] then [[img:bbb]] and [[img:ccc]] done"
    clean, ids = parse_images(text)
    assert clean == "First  then  and  done"
    assert ids == ["aaa", "bbb", "ccc"]


def test_parse_images_malformed_no_id():
    """[[img:]] with empty ID is ignored by the regex."""
    clean, ids = parse_images("before [[img:]] after")
    assert clean == "before [[img:]] after"
    assert ids == []


def test_parse_images_malformed_space_in_id():
    """[[img: ]] — space in ID is rejected by [a-zA-Z0-9_-]+."""
    clean, ids = parse_images("before [[img: ]] after")
    assert clean == "before [[img: ]] after"
    assert ids == []


def test_parse_images_malformed_invalid_chars():
    """[[img:a b]] — space inside ID is rejected."""
    clean, ids = parse_images("before [[img:a b]] after")
    assert clean == "before [[img:a b]] after"
    assert ids == []


def test_parse_images_placeholder_at_start():
    clean, ids = parse_images("[[img:abc]] hello world")
    assert clean == " hello world"
    assert ids == ["abc"]


def test_parse_images_placeholder_at_end():
    clean, ids = parse_images("hello world [[img:xyz]]")
    assert clean == "hello world "
    assert ids == ["xyz"]


def test_parse_images_regex_accepts_hyphens_and_underscores():
    """IDs with hyphens and underscores are accepted."""
    clean, ids = parse_images("[[img:my-image_id]]")
    assert clean == ""
    assert ids == ["my-image_id"]


def test_parse_images_multiple_on_same_line():
    clean, ids = parse_images("A [[img:1]] B [[img:2]] C [[img:3]] D")
    assert clean == "A  B  C  D"
    assert ids == ["1", "2", "3"]


def test_parse_images_only_placeholders():
    clean, ids = parse_images("[[img:a]][[img:b]]")
    assert clean == ""
    assert ids == ["a", "b"]
