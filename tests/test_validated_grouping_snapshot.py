"""Grouping normalization and owner-scoped immutable handoff contracts."""
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal
import inspect
import sys

import pytest

from metroliza.industrial.contracts import (
    IndustrialAnalyticsRequest, validate_industrial_analytics_request,
)
from metroliza.tabular.contracts import (
    GroupingAssignment, _GroupingSnapshotOwner, _ValidatedGroupingSnapshot,
    validate_grouping_df,
)


@pytest.mark.parametrize('record, expected', [
    ({'REPORT_ID': 1, 'Group': 'a', 'group': 'b', 'gRoUp': 'c'}, 'c'),
    ({'REPORT_ID': 1, 'GROUP': None, 'group': 'b', 'gRoUp': 'c'}, 'POPULATION'),
    ({'REPORT_ID': 1, 'GROUP': 'a', 'group': 'b', 'gRoUp': 'c'}, 'a'),
    ({'REPORT_ID': '١', 'group': ' Straße '}, 'Straße'),
    ({'REPORT_ID': Decimal('2.0'), 'group': 'İ'}, 'İ'),
])
def test_alias_order_and_exact_none(record, expected):
    result = validate_grouping_df(record)
    assert type(result) is tuple
    assert type(result[0]) is GroupingAssignment
    assert result[0].group == expected
    assert type(result[0].report_id) is int


@pytest.mark.parametrize('value', [True, False, None, 0, -1, '1.5', Decimal('NaN'),
                                   float('inf'), 2**63, '1\x00'])
def test_public_assignment_tuple_is_untrusted(value):
    request = IndustrialAnalyticsRequest(
        source_kind='tabular_file', output_dashboard_file='result.html',
        grouping_df=(GroupingAssignment(group='A', report_id=value),),
    )
    with pytest.raises(ValueError, match='must include REPORT_ID'):
        validate_industrial_analytics_request(request)


def test_snapshot_is_issued_immutable_and_revision_bound():
    source = [{'REPORT_ID': 2, 'GROUP': 'A', 'REFERENCE': ' r '},
              {'REPORT_ID': 1, 'GROUP': 'B', 'GROUP_COLOR': 'blue'}]
    owner = _GroupingSnapshotOwner()
    assignments, snapshot = owner.capture(source)
    assert snapshot.resolve(assignments) is assignments
    assert assignments == (GroupingAssignment('A', 2, reference='r'),
                           GroupingAssignment('B', 1, group_color='blue'))
    source[0]['GROUP'] = 'mutated'
    assert snapshot.resolve(assignments)[0].group == 'A'
    with pytest.raises(FrozenInstanceError):
        snapshot.assignments = ()
    with pytest.raises(FrozenInstanceError):
        assignments[0].group = 'mutated'
    for bad in (replace(snapshot, assignments=(GroupingAssignment('A', True),)),
                replace(snapshot, revision=snapshot.revision + 1),
                replace(snapshot, _owner=None)):
        with pytest.raises(ValueError, match='stale'):
            bad.resolve(bad.assignments)
    owner.invalidate()
    with pytest.raises(ValueError, match='stale'):
        snapshot.resolve(assignments)
    _, newer = owner.capture(source)
    assert newer.revision > snapshot.revision
    assert newer.assignments[0].group == 'mutated'


def test_snapshot_validation_still_checks_independent_request_fields():
    owner = _GroupingSnapshotOwner()
    values, snapshot = owner.capture({'REPORT_ID': 1, 'GROUP': 'A'})
    request = IndustrialAnalyticsRequest(
        source_kind='tabular_file', output_dashboard_file='result.html',
        grouping_df=values, _grouping_snapshot=snapshot,
    )
    assert validate_industrial_analytics_request(request).grouping_df is values
    with pytest.raises(ValueError, match='Select a CSV or Excel file'):
        validate_industrial_analytics_request(request, require_runnable=True)
    with pytest.raises(ValueError, match='must use the .html extension'):
        validate_industrial_analytics_request(replace(request, output_dashboard_file='bad.pdf'))
    with pytest.raises(ValueError, match='stale'):
        validate_industrial_analytics_request(replace(request, grouping_df=()))
    forged = _ValidatedGroupingSnapshot(
        (GroupingAssignment('bad', True),), 'POPULATION', 0, 0, owner,
    )
    with pytest.raises(ValueError, match='stale'):
        validate_industrial_analytics_request(replace(
            request, grouping_df=forged.assignments, _grouping_snapshot=forged,
        ))


def test_plain_records_build_lower_mapping_once_and_custom_keys_keep_callbacks(monkeypatch):
    from metroliza.tabular import contracts
    original = contracts._record_value
    calls = []
    def lookup(*args):
        calls.append(args[1:])
        return original(*args)
    monkeypatch.setattr(contracts, '_record_value', lookup)
    maps, previous = [], sys.getprofile()
    def count_maps(frame, event, _arg):
        if (event == 'call' and frame.f_code.co_name == '<dictcomp>'
                and frame.f_back.f_code is contracts._plain_record_values.__code__):
            maps.append(frame.f_code)
    try:
        sys.setprofile(count_maps)
        validate_grouping_df({'REPORT_ID': 1, 'group': 'A', 'Group': None})
    finally:
        sys.setprofile(previous)
    assert len(maps) == 1
    assert calls == []
    events = []
    class Key(str):
        def __str__(self):
            events.append('str')
            return str.__str__(self)
    validate_grouping_df({Key('REPORT_ID'): 1, Key('GROUP'): 'A'})
    assert len(calls) == 8
    assert events == ['str'] * 16


@pytest.mark.parametrize('field', [item.name for item in fields(GroupingAssignment)])
@pytest.mark.parametrize('pairs, expected', [
    ([('lower', 1), ('mixed', None)], 1),
    ([('mixed', None), ('lower', 1)], 1),
    ([('upper', None), ('lower', 2)], None),
    ([('lower', 2), ('upper', None)], None),
    ([('lower', None), ('mixed', 2)], 2),
    ([('mixed', 1), ('lower', 2)], 2),
    ([('lower', 1), ('mixed', 2)], 2),
    ([('upper', 1), ('mixed', 2)], 1),
    ([('upper', 1)], 1),
    ([('mixed', None)], None),
    ([], None),
])
@pytest.mark.parametrize('custom', [False, True])
def test_every_field_preserves_ordered_alias_none_and_collision_semantics(field, pairs, expected, custom):
    from collections import UserDict
    events = []
    class Record(UserDict):
        def items(self):
            events.append('items')
            return super().items()
    aliases = {'upper': field.upper(), 'lower': field, 'mixed': field.title()}
    values = {None: None, 1: 1 if field == 'report_id' else 'A',
              2: 2 if field == 'report_id' else 'B'}
    record = {'REPORT_ID': 1, 'GROUP': 'base'}
    record.pop(field.upper(), None)
    record.update((aliases[key], values[value]) for key, value in pairs)
    source = Record(record) if custom else record
    if field == 'report_id' and expected is None:
        with pytest.raises(ValueError, match='^Grouping assignments must include REPORT_ID\\.$'):
            validate_grouping_df(source)
        lookups = 2
    else:
        result = validate_grouping_df(source)
        value = values[expected] if expected is not None else 'POPULATION' if field == 'group' else None
        assert type(result) is tuple and type(result[0]) is GroupingAssignment
        assert result == (replace(GroupingAssignment('base', 1), **{field: value}),)
        assert type(getattr(result[0], field)) is type(value)
        lookups = 8
    assert events == (['items'] * lookups if custom else [])


def test_value_callbacks_can_mutate_later_fields_before_their_lookup():
    record = {'REPORT_ID': 1, 'GROUP': None, 'REFERENCE': 'before'}
    class Group:
        def __str__(self):
            record['REFERENCE'] = 'after'
            return 'A'
    record['GROUP'] = Group()
    assert validate_grouping_df(record) == (GroupingAssignment('A', 1, reference='after'),)


def test_request_keeps_historical_public_positional_and_matching_contract():
    public_fields = [item for item in fields(IndustrialAnalyticsRequest)
                     if not item.name.startswith('_')]
    names = tuple(item.name for item in public_fields)
    defaults = IndustrialAnalyticsRequest('tabular_file', 'result.html')
    args = [getattr(defaults, name) for name in names]
    visual, interactivity = {'background': 'sentinel'}, {'mode': 'static'}
    args[names.index('dashboard_visual_settings')] = visual
    args[names.index('dashboard_interactivity_options')] = interactivity
    request = IndustrialAnalyticsRequest(*args)
    assert request.dashboard_visual_settings is visual
    assert request.dashboard_interactivity_options is interactivity
    assert names[-2:] == ('dashboard_visual_settings', 'dashboard_interactivity_options')
    assert IndustrialAnalyticsRequest.__match_args__ == names
    signature = inspect.signature(IndustrialAnalyticsRequest)
    for name in ('_grouping_snapshot', '_grouping_owner'):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize('kind', ['value', 'key', 'mapping', 'frame_subclass',
                                  'frame_method', 'row_method', 'object_frame', 'label', 'attrs'])
def test_raw_callback_provenance_declines_even_when_normalized_values_are_plain(kind):
    import pandas as pd
    from collections import UserDict
    from metroliza.analytics.row_table import RowTable
    class Text(str):
        pass
    class Frame(pd.DataFrame):
        pass
    source = {'REPORT_ID': 1, 'GROUP': 'A'}
    if kind == 'value':
        source['GROUP'] = Text('A')
    elif kind == 'key':
        source = {Text('REPORT_ID'): 1, 'GROUP': 'A'}
    elif kind == 'mapping':
        source = UserDict(source)
    elif kind in ('frame_subclass', 'frame_method', 'object_frame'):
        source = (Frame if kind == 'frame_subclass' else pd.DataFrame)([source])
        if kind == 'frame_method':
            source.to_dict = lambda *args: [{'REPORT_ID': 1, 'GROUP': 'A'}]
        elif kind == 'object_frame':
            source = source.astype(object)
    else:
        source = RowTable(((1, 'A'),), ('REPORT_ID', 'GROUP'))
        if kind == 'row_method':
            source.iter_rows = lambda **kwargs: iter([{'REPORT_ID': 1, 'GROUP': 'A'}])
        elif kind == 'label':
            source.default_group_label = Text('Rest')
        else:
            source.attrs = UserDict(default_group_label='Rest')
    values, snapshot = _GroupingSnapshotOwner().capture(source)
    assert values[0].group == 'A'
    assert snapshot is None


@pytest.mark.parametrize('kind', ['dict', 'frame', 'row_table'])
def test_ordinary_raw_sources_activate_without_revalidating(kind):
    import pandas as pd
    from metroliza.analytics.row_table import RowTable
    source = {'REPORT_ID': 1, 'GROUP': 'A'}
    if kind == 'frame':
        source = pd.DataFrame([source])
    elif kind == 'row_table':
        source = RowTable(((1, 'A'),), ('REPORT_ID', 'GROUP'))
    values, snapshot = _GroupingSnapshotOwner().capture(source)
    assert snapshot is not None
    assert snapshot.resolve(values)[0].group == 'A'


def test_declined_metadata_is_derived_once_in_each_original_validation():
    from metroliza.analytics.row_table import RowTable
    calls = []
    class Label:
        def __str__(self):
            calls.append('label')
            return f'Rest{len(calls)}'
    source = RowTable(((1, 'A'),), ('REPORT_ID', 'GROUP'), Label())
    request = validate_industrial_analytics_request(IndustrialAnalyticsRequest(
        'tabular_file', 'result.html', grouping_df=source,
        _grouping_owner=_GroupingSnapshotOwner(),
    ))
    assert request._grouping_snapshot is None
    assert request.grouping_default_group_label == 'Rest1'
    assert calls == ['label']


@pytest.mark.parametrize('already_declined', [False, True])
def test_custom_axis_cache_keeps_original_callback_free_fallback(already_declined):
    import pandas as pd
    import warnings
    calls = []
    class Cache(dict):
        def get(self, key, *default):
            calls.append(key)
            warnings.warn('custom cache callback', UserWarning)
            return super().get(key, *default)
    class Label(str):
        pass
    source = pd.DataFrame({'REPORT_ID': [1], 'GROUP': ['A']})
    if already_declined:
        source.attrs['default_group_label'] = Label('Rest')
    source.columns._cache = Cache(source.columns._cache)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        values, snapshot = _GroupingSnapshotOwner().capture(source)
    assert values == (GroupingAssignment('A', 1),)
    assert snapshot is None
    assert calls == []
    assert captured == []


@pytest.mark.parametrize('kind', ['frame', 'axis', 'rowtable', 'assignment'])
@pytest.mark.parametrize('raising', [False, True])
def test_raw_metadata_dictionaries_decline_before_added_dispatch(kind, raising):
    import pandas as pd
    import warnings
    from metroliza.analytics.row_table import RowTable
    events = []
    class State(dict):
        def get(self, key, default=None):
            events.append(('get', key))
            warnings.warn('raw-state-get', UserWarning)
            if raising:
                raise RuntimeError('raw-state-get')
            return super().get(key, default)
        def keys(self):
            events.append(('keys',))
            warnings.warn('raw-state-keys', UserWarning)
            if raising:
                raise RuntimeError('raw-state-keys')
            return super().keys()
    if kind == 'rowtable':
        source = RowTable(((1, 'A'),), ('REPORT_ID', 'GROUP'))
    elif kind == 'assignment':
        source = GroupingAssignment('A', 1)
    else:
        source = pd.DataFrame({'REPORT_ID': [1], 'GROUP': ['A']})
    target = source.columns if kind == 'axis' else source
    object.__setattr__(target, '__dict__', State(vars(target)))
    owner = _GroupingSnapshotOwner()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        values, snapshot = owner.capture(source)
    assert values == (GroupingAssignment('A', 1),)
    assert snapshot is None and owner.default_group_label == 'POPULATION'
    assert events == [] and caught == []


@pytest.mark.parametrize('kind', ['source_key', 'axis_key', 'manager_method',
                                  'manager_state', 'axes', 'blocks', 'block_state',
                                  'string_state', 'string_method'])
def test_nested_raw_storage_declines_without_eligibility_callbacks(kind):
    import pandas as pd
    from metroliza.tabular import contracts
    source = pd.DataFrame({'REPORT_ID': [1], 'GROUP': ['A']})
    events = []
    class Key(str):
        def __hash__(self):
            events.append('hash')
            return super().__hash__()
        def __eq__(self, other):
            events.append('eq')
            return super().__eq__(other)
    class State(dict):
        def keys(self):
            events.append('keys')
            return super().keys()
        def get(self, *args):
            events.append('get')
            return super().get(*args)
        def values(self):
            events.append('values')
            return super().values()
    class Axes(list):
        def __iter__(self):
            events.append('axes')
            return super().__iter__()
    class Blocks(tuple):
        def __iter__(self):
            events.append('blocks')
            return super().__iter__()
    manager = source._mgr
    if kind.endswith('_key'):
        target = source if kind == 'source_key' else source.columns
        vars(target)[Key('custom')] = True
    elif kind == 'manager_method':
        manager.iget = lambda *args: events.append('iget')
    elif kind in ('axes', 'blocks'):
        original = getattr(manager, kind)
        replacement = Axes(original) if kind == 'axes' else Blocks(original)
        native = 'list' if kind == 'axes' else 'tuple'
        with pytest.raises(TypeError, match=f'^Expected {native}, got {type(replacement).__name__}$'):
            setattr(manager, kind, replacement)
        assert getattr(manager, kind) is original
        assert contracts._raw_grouping_source(source) is True
        assert events == []
        return
    else:
        strings = next(block.values for block in manager.blocks
                       if type(block).__name__ == 'ExtensionBlock')
        target = {'manager_state': manager, 'block_state': manager.blocks[0],
                  'string_state': strings, 'string_method': strings}[kind]
        if kind == 'string_method':
            target.to_numpy = lambda *args: events.append('to_numpy')
        else:
            object.__setattr__(target, '__dict__', State(vars(target)))
    events.clear()
    assert contracts._raw_grouping_source(source) is False
    assert events == []


def test_native_constructor_string_storage_keeps_snapshot_and_request_activation(monkeypatch):
    import pandas as pd
    from metroliza.tabular import contracts
    source = pd.DataFrame({'REPORT_ID': [1], 'GROUP': ['A']})
    assert type(source['GROUP'].array) is pd.arrays.StringArray
    values, snapshot = _GroupingSnapshotOwner().capture(source)
    assert snapshot is not None and snapshot.resolve(values) is values
    def unexpected_validation(*args, **kwargs):
        raise AssertionError('issued values must not be revalidated')
    monkeypatch.setattr(contracts, '_validate_grouping_assignments', unexpected_validation)
    request = IndustrialAnalyticsRequest('tabular_file', 'result.html',
                                        grouping_df=values, _grouping_snapshot=snapshot)
    assert validate_industrial_analytics_request(request).grouping_df is values


@pytest.mark.parametrize('kind', ['source', 'axis', 'cache'])
def test_post_conversion_provenance_rechecks_raw_metadata(monkeypatch, kind):
    import pandas as pd
    source = pd.DataFrame({'REPORT_ID': [1], 'GROUP': ['A']})
    original = pd.DataFrame.to_dict
    events = []
    class State(dict):
        def get(self, *args):
            events.append('get')
            raise RuntimeError('late metadata get')
        def keys(self):
            events.append('keys')
            raise RuntimeError('late metadata keys')
    def convert(frame, *args, **kwargs):
        records = original(frame, *args, **kwargs)
        target = frame if kind == 'source' else frame.columns
        if kind == 'cache':
            target._cache = State(target._cache)
        else:
            object.__setattr__(target, '__dict__', State(vars(target)))
        return records
    monkeypatch.setattr(pd.DataFrame, 'to_dict', convert)
    values, snapshot = _GroupingSnapshotOwner().capture(source)
    assert values == (GroupingAssignment('A', 1),) and snapshot is None
    assert events == []
