"""P3 number parsing, unit registry and semantic context tests."""

from decimal import Decimal

from dalel.pillars.quantitative_consistency.normalization import (
    fold_superscripts,
    normalize_label,
    normalize_unit_text,
)
from dalel.pillars.quantitative_consistency.number_parser import (
    decimal_str,
    scan_text,
    unambiguous_decimal_style,
)
from dalel.pillars.quantitative_consistency.semantic_context import (
    classify_metric,
    extract_period,
    extract_qualifiers,
    extract_source_key,
    extract_substance,
    is_subset_label,
    is_total_label,
    substance_from_code,
)
from dalel.pillars.quantitative_consistency.units import (
    convert_to_canonical,
    convertible,
    dimension_key,
    lookup_unit,
)


def _single(text: str, style: str | None = None):
    result = scan_text(text, style)
    assert len(result.spans) == 1, (text, result.spans, result.suppressed)
    return result.spans[0]


def _suppressed_reasons(text: str, style: str | None = None) -> set[str]:
    return {item.reason for item in scan_text(text, style).suppressed}


# --- number formats ------------------------------------------------------------


def test_decimal_comma_and_dot() -> None:
    assert _single("масса 12,4 т").value == Decimal("12.4")
    assert _single("масса 12.4 т").value == Decimal("12.4")


def test_thousands_separators() -> None:
    assert _single("объем 1 234,5 м3").value == Decimal("1234.5")
    assert _single("выпуск 1.234.567 шт").value == Decimal("1234567")
    assert _single("выпуск 1,234,567.25 шт").value == Decimal("1234567.25")


def test_non_breaking_space_grouping() -> None:
    assert _single("энергия 35 680 кВт").value == Decimal("35680")
    assert _single("энергия 35 680 кВт").value == Decimal("35680")


def test_negative_value() -> None:
    span = _single("температура: -5,2 °С")
    assert span.value == Decimal("-5.2")
    assert span.unit is not None and span.unit.kind == "temperature"


def test_dash_as_key_value_separator_is_not_a_sign() -> None:
    # Corpus idiom: «Количество ПГС -7,2 т» means "quantity: 7.2 t".
    span = _single("Количество ПГС -7,2 т")
    assert span.value == Decimal("7.2")


def test_scientific_notation_comma_mantissa() -> None:
    span = _single("выброс 2,744E-05 г/с")
    assert span.value == Decimal("0.00002744")
    assert span.display_quantum == Decimal("1E-8")


def test_power_notation_with_exponent() -> None:
    span = _single("значение 1,5 · 10^3 мг")
    assert span.value == Decimal("1500")
    assert "power_notation" in span.flags


def test_lost_exponent_suppressed() -> None:
    reasons = _suppressed_reasons("значение 20 · 10 мг")
    assert "missing_scientific_exponent" in reasons


def test_percentage_forms() -> None:
    span = _single("доля 56.2%")
    assert span.unit is not None and span.unit.kind == "percent"
    span = _single("доля 5 %")
    assert span.unit is not None and span.unit.kind == "percent"


def test_leading_separator_decimal() -> None:
    span = _single("значение .5 мг/м3")
    assert span.value == Decimal("0.5")
    assert "leading_separator" in span.flags


def test_range_ot_do() -> None:
    span = _single("от 10 до 12 мг/м3")
    assert span.kind == "range"
    assert (span.low, span.high) == (Decimal("10"), Decimal("12"))


def test_range_dash_with_unit() -> None:
    span = _single("выброс 10-12 т/год")
    assert span.kind == "range"
    assert (span.low, span.high) == (Decimal("10"), Decimal("12"))


def test_bare_integer_dash_pair_suppressed() -> None:
    assert "unitless_dash_pair" in _suppressed_reasons("источники 6701-703 и другие")


def test_inequalities_and_bounds() -> None:
    upper = _single("не более 200 тонн в год")
    assert upper.modifier == "upper_bound" and upper.bound_inclusive is True
    lower = _single("не менее 5 га")
    assert lower.modifier == "lower_bound" and lower.bound_inclusive is True
    strict = _single("< 5 мг/м3")
    assert strict.modifier == "upper_bound" and strict.bound_inclusive is False
    do = _single("до 100 т")
    assert do.modifier == "upper_bound"
    svyshe = _single("свыше 30 га")
    assert svyshe.modifier == "lower_bound" and svyshe.bound_inclusive is False
    kk = _single("10 т аспайды")
    assert kk.modifier == "upper_bound"


def test_approximation_markers() -> None:
    for text in ("около 800 мм", "примерно 800 мм", "шамамен 800 мм", "~800 мм"):
        span = _single(text)
        assert span.modifier == "approximate", text


def test_ambiguous_1234_depends_on_doc_style() -> None:
    comma_doc = _single("масса 1,234 т", "comma")
    assert "ambiguous_decimal_grouping" not in comma_doc.flags
    assert comma_doc.value == Decimal("1.234")
    # Dot decimal style alone is NOT enough for a thousands reading — the
    # corpus mixes decimal conventions within documents.
    dot_doc = _single("масса 1,234 т", "dot")
    assert "ambiguous_decimal_grouping" in dot_doc.flags
    unknown = _single("масса 1,234 т", None)
    assert "ambiguous_decimal_grouping" in unknown.flags  # unresolved


def test_document_style_detection() -> None:
    assert unambiguous_decimal_style("0,5 и 1,25 и 3.14") == "comma"
    assert unambiguous_decimal_style("0.5 и 1.25 и 3,14") == "dot"
    assert unambiguous_decimal_style("0,5 и 1.25") is None


# --- false-positive identifier suppression ----------------------------------------


def test_year_suppression() -> None:
    assert "year_word" in _suppressed_reasons("в 2025 году")
    assert "bare_year_like" in _suppressed_reasons("показатель 2030 без единицы")
    assert "year_range" in _suppressed_reasons("на 2025-2034 гг.")
    assert "year_abbreviation_gram_collision" in _suppressed_reasons("в марте 2024 г. выполнено")


def test_year_with_real_unit_kept() -> None:
    span = _single("объем 2030 т/год")
    assert span.value == Decimal("2030")


def test_page_and_section_references_suppressed() -> None:
    reasons = _suppressed_reasons("см. стр. 15 и раздел 3.2.1")
    assert "reference_identifier" in reasons
    assert "structural_numbering" in reasons


def test_document_numbers_and_gost() -> None:
    assert "reference_identifier" in _suppressed_reasons("приказ № 123")
    assert _suppressed_reasons("ГОСТ 12.1.005-88")  # suppressed, no quantity spans
    assert not scan_text("ГОСТ 12.1.005-88").spans


def test_phone_and_bin_suppressed() -> None:
    reasons = _suppressed_reasons("тел. 8-705-908-35-30, БИН 111 240 003 333")
    assert "identifier_sequence" in reasons
    assert not scan_text("тел. 8-705-908-35-30").spans


def test_dates_suppressed() -> None:
    assert "date" in _suppressed_reasons("от 12.05.2025 действует")
    assert "date" in _suppressed_reasons("подписано 3 января 2026 года")


def test_coordinates_suppressed() -> None:
    result = scan_text("координаты 47⁰ 04'26.7\" СШ")
    assert {s.reason for s in result.suppressed} == {"coordinate"}
    assert not result.spans


def test_zero_padded_codes_suppressed() -> None:
    assert "zero_padded_code" in _suppressed_reasons("код 0301 вещества")
    assert "source_code_pair" in _suppressed_reasons("источник 6001-001")


def test_model_identifier_suppressed() -> None:
    assert "model_identifier" in _suppressed_reasons("котел КС-135 установлен")


def test_formula_variable_suppressed() -> None:
    reasons = _suppressed_reasons("К=0,2 Т - время работы")
    assert "formula_variable" in reasons


def test_zero_is_a_valid_quantity() -> None:
    assert _single("выброс 0 т/год").value == Decimal("0")


def test_range_inversion_flag_with_unit() -> None:
    span = _single("диапазон 3–2 кг/год")
    assert span.kind == "range" and "range_inversion" in span.flags


# --- decimal_str -------------------------------------------------------------------


def test_decimal_str_canonical() -> None:
    assert decimal_str(Decimal("1.20")) == "1.2"
    assert decimal_str(Decimal("1.2E+6")) == "1200000"
    assert decimal_str(Decimal("-0")) == "0"
    assert decimal_str(Decimal("0.00002744")) == "0.00002744"


# --- units ---------------------------------------------------------------------------


def test_unit_aliases_russian_kazakh_english() -> None:
    assert lookup_unit("т/год").canonical == "т/год"
    assert lookup_unit("т/жыл").canonical == "т/год"
    assert lookup_unit("t/year").canonical == "т/год"
    assert lookup_unit("тонн в год").canonical == "т/год"
    assert lookup_unit("кг/тәулік").canonical == "кг/сут"
    assert lookup_unit("пайыз").canonical == "%"


def test_unit_unicode_and_ascii_forms() -> None:
    assert lookup_unit("мг/м³") == lookup_unit("мг/м3")
    assert lookup_unit("м²") == lookup_unit("м2")
    assert lookup_unit("тыс. м³") == lookup_unit("тыс.м3")
    assert lookup_unit("тыс,м3") == lookup_unit("тыс. м3")  # OCR comma corruption


def test_unit_latin_homoglyph() -> None:
    assert lookup_unit("г/c").canonical == "г/с"  # latin c


def test_mass_conversions() -> None:
    tonne = lookup_unit("т")
    assert convert_to_canonical(Decimal("1.2"), tonne) == Decimal("1200000")  # grams
    kg = lookup_unit("кг")
    assert convert_to_canonical(Decimal("900"), kg) == Decimal("900000")


def test_rate_conversion_same_time_basis() -> None:
    t_year = lookup_unit("т/год")
    kg_year = lookup_unit("кг/год")
    assert convertible(t_year, kg_year)
    assert convert_to_canonical(Decimal("1.2"), t_year) == Decimal("1200000")
    assert convert_to_canonical(Decimal("1200"), kg_year) == Decimal("1200000")


def test_rate_time_bases_not_convertible() -> None:
    assert not convertible(lookup_unit("г/с"), lookup_unit("т/год"))
    assert not convertible(lookup_unit("кг/ч"), lookup_unit("кг/сут"))


def test_volume_scale_conversions() -> None:
    thousand = lookup_unit("тыс. м3")
    assert convert_to_canonical(Decimal("2.5"), thousand) == Decimal("2500")
    litre = lookup_unit("л")
    assert convert_to_canonical(Decimal("500"), litre) == Decimal("0.5")


def test_concentration_conversions() -> None:
    mg_l = lookup_unit("мг/л")
    assert convert_to_canonical(Decimal("1"), mg_l) == Decimal("1000")  # mg/m3
    assert lookup_unit("мг/дм3") == mg_l


def test_normal_conditions_not_convertible_to_actual() -> None:
    assert not convertible(lookup_unit("мг/нм3"), lookup_unit("мг/м3"))


def test_incompatible_dimensions() -> None:
    assert not convertible(lookup_unit("т"), lookup_unit("м3"))
    assert not convertible(lookup_unit("га"), lookup_unit("т/год"))


def test_dimension_keys() -> None:
    assert dimension_key(lookup_unit("т/год")) == "mass_rate/year"
    assert dimension_key(lookup_unit("га")) == "area"


def test_raw_unit_preserved_in_span() -> None:
    span = _single("выброс 1,2 тонн в год")
    assert span.unit_raw == "тонн в год"
    assert span.unit.canonical == "т/год"


def test_uppercase_single_letter_not_a_unit() -> None:
    result = scan_text("К=0,2 Т - фактическое время")
    assert all(s.unit is None or len(s.unit.canonical) > 1 for s in result.spans)


def test_unit_not_matched_inside_word() -> None:
    span = _single("выход 5 газов")  # «га» must not match inside «газов»
    assert span.unit is None


# --- normalization helpers ------------------------------------------------------------


def test_superscript_folding() -> None:
    assert fold_superscripts("10⁵") == "10^5"
    assert fold_superscripts("м³") == "м3"
    assert fold_superscripts("47⁰ 04'") == "47° 04'"


def test_normalize_unit_text() -> None:
    assert normalize_unit_text("Тыс. М³") == "тысм3"
    assert normalize_unit_text("т / год".replace(" ", "")) == "т/год"


def test_normalize_label() -> None:
    assert normalize_label("Валовый  ВЫБРОС, т/год:") == "валовый выброс т год"


# --- semantic context --------------------------------------------------------------------


def test_classify_metric() -> None:
    assert classify_metric("Валовый выброс загрязняющих веществ") == "emission"
    assert classify_metric("Образование отходов") == "waste"
    assert classify_metric("Водопотребление на нужды") == "water_use"
    assert classify_metric("Совершенно нейтральный текст") is None


def test_extract_substance_with_case_forms() -> None:
    assert extract_substance("выброс диоксида азота") == "no2"
    assert extract_substance("Азота диоксид") == "no2"
    assert extract_substance("оксид углерода") == "co"
    assert extract_substance("сажа") == "soot"
    assert extract_substance("обычный текст") is None


def test_dust_classes_stay_distinct() -> None:
    a = extract_substance("Пыль неорганическая, содержащая двуокись кремния в %: 70-20")
    b = extract_substance("Пыль неорганическая: до 20% SiO2")
    c = extract_substance("Пыль неорганическая, выше 70% SiO2")
    assert (a, b, c) == ("dust_sio2_20_70", "dust_sio2_below_20", "dust_sio2_above_70")
    assert len({a, b, c}) == 3


def test_substance_from_code() -> None:
    assert substance_from_code("0301") == "no2"
    assert substance_from_code("301") == "no2"  # zero-padded lookup
    assert substance_from_code("1234") == "code_1234"  # unmapped but stable
    assert substance_from_code("abc") is None


def test_qualifiers() -> None:
    assert extract_qualifiers("максимально разовый выброс") == {"max_onetime"}
    assert extract_qualifiers("планируемый валовый выброс") == {"planned", "gross"}
    assert extract_qualifiers("выброс с учетом очистки") == {"with_treatment"}


def test_period_extraction() -> None:
    assert extract_period("выбросы за 2025 год") == "y2025"
    assert extract_period("на 2025-2034 годы") == "y2025_2034"
    assert extract_period("во II квартале 2026") == "y2026-q2"
    assert extract_period("без периода") is None


def test_source_key_extraction() -> None:
    assert extract_source_key("Маслопресс - источник №0003") == "0003"
    assert extract_source_key("выбросы источника 6001") == "6001"
    assert extract_source_key("обычный заголовок") is None


def test_total_and_subset_labels() -> None:
    assert is_total_label("Итого:")
    assert is_total_label("ВСЕГО по загрязняющему веществу:")
    assert is_total_label("Барлығы")
    assert not is_total_label("Азота диоксид")
    assert is_subset_label("в том числе:")
    assert is_subset_label("из них")
    assert not is_subset_label("Итого")
