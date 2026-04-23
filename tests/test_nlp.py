from app.services.nlp import entities_to_search_boost, extract_entities


def test_extract_entities_finds_material_target_flavor_and_size():
    entities = extract_entities("Mens stainless steel coffee bottle 500ml")

    assert entities.target == "mens"
    assert entities.material == "steel"
    assert entities.flavor == "coffee"
    assert entities.size == "500ml"
    assert "73" in entities.chapter_hint


def test_entities_to_search_boost_returns_boost_terms_and_hints():
    entities = extract_entities("Kerala kids cotton chocolate drink 1kg")
    boost = entities_to_search_boost(entities)

    assert boost["brand"] is None
    assert boost["has_size"] is True
    assert boost["chapter_hints"] == ["61", "62", "63"]
    assert boost["boost_terms"] == ["baby", "textile", "chocolate", "kerala"]
