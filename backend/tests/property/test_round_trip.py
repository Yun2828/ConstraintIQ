"""Property test for GeometricModel round-trip fidelity.

Feature: engineering-drawing-analyzer
Property 1: Geometric Model Round-Trip Fidelity

Validates: Requirements 1.2, 1.5, 1.6
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from engineering_drawing_analyzer.models import (
    Datum,
    Dimension,
    DrawingFormat,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    LocationReference,
    Point2D,
    TitleBlock,
    Tolerance,
    View,
)
from engineering_drawing_analyzer.serializer import (
    GeometricModelSerializer,
    models_equivalent,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

st_float = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e9, max_value=1e9)
st_text = st.text(min_size=0, max_size=50)
st_nonempty_text = st.text(min_size=1, max_size=50)

st_point = st.builds(Point2D, x=st_float, y=st_float)

st_location = st.builds(
    LocationReference,
    view_name=st_nonempty_text,
    coordinates=st.one_of(st.none(), st_point),
    label=st.one_of(st.none(), st_text),
)

st_tolerance = st.builds(
    Tolerance,
    upper=st_float,
    lower=st_float,
    is_general=st.booleans(),
)

st_dimension = st.builds(
    Dimension,
    id=st_nonempty_text,
    value=st_float,
    unit=st.sampled_from(["mm", "in"]),
    tolerance=st.one_of(st.none(), st_tolerance),
    location=st_location,
    associated_feature_ids=st.lists(st_nonempty_text, max_size=5),
)

st_fcf = st.builds(
    FeatureControlFrame,
    id=st_nonempty_text,
    gdt_symbol=st_nonempty_text,
    tolerance_value=st.one_of(st.none(), st_float),
    datum_references=st.lists(st_nonempty_text, max_size=3),
    material_condition=st.one_of(st.none(), st.sampled_from(["MMC", "LMC", "RFS"])),
    location=st_location,
)

st_datum = st.builds(
    Datum,
    label=st_nonempty_text,
    feature_id=st_nonempty_text,
    location=st_location,
)

st_feature = st.builds(
    Feature,
    id=st_nonempty_text,
    feature_type=st.sampled_from(["HOLE", "SLOT", "SURFACE", "EDGE"]),
    dimensions=st.lists(st_dimension, max_size=5),
    feature_control_frames=st.lists(st_fcf, max_size=3),
    location=st.one_of(st.none(), st_location),
    is_angular=st.booleans(),
    is_threaded=st.booleans(),
    is_blind_hole=st.booleans(),
    ml_confidence=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
    ml_symbol_type=st.one_of(st.none(), st_text),
)

st_title_block = st.builds(
    TitleBlock,
    part_number=st.one_of(st.none(), st_text),
    revision=st.one_of(st.none(), st_text),
    material=st.one_of(st.none(), st_text),
    scale=st.one_of(st.none(), st_text),
    units=st.one_of(st.none(), st_text),
)

st_view = st.builds(
    View,
    name=st_nonempty_text,
    features=st.lists(st_nonempty_text, max_size=5),
)

st_geometric_model = st.builds(
    GeometricModel,
    schema_version=st.just("1.0"),
    source_format=st.sampled_from(list(DrawingFormat)),
    features=st.lists(st_feature, max_size=10),
    dimensions=st.lists(st_dimension, max_size=10),
    datums=st.lists(st_datum, max_size=5),
    feature_control_frames=st.lists(st_fcf, max_size=5),
    title_block=st.one_of(st.none(), st_title_block),
    views=st.lists(st_view, max_size=5),
    general_tolerance=st.one_of(st.none(), st_tolerance),
    notes=st.lists(st_text, max_size=5),
)


# ---------------------------------------------------------------------------
# Property 1: Round-Trip Fidelity
# ---------------------------------------------------------------------------


@given(st_geometric_model)
@settings(max_examples=100)
def test_round_trip_fidelity(model: GeometricModel) -> None:
    """**Validates: Requirements 1.2, 1.5, 1.6**

    For any GeometricModel, serialize → deserialize must produce a
    structurally equivalent model.
    """
    serializer = GeometricModelSerializer()
    serialized = serializer.serialize(model)
    restored = serializer.deserialize(serialized)
    assert models_equivalent(model, restored), (
        f"Round-trip produced a non-equivalent model.\n"
        f"Original source_format: {model.source_format}\n"
        f"Restored source_format: {restored.source_format}"
    )
