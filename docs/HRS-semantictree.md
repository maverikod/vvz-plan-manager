# CHANGE REQUEST: исправить алгоритм semantic coverage в `planmgr`

## ID

`CR-PLANMGR-BRANCH-COVERAGE-SCOPE-AWARE-001`

## Связанный баг

`BUG-PLANMGR-COVERAGE-ESTIMATOR-USES-GS-LABELS-TO-OVERREQUIRE-BRANCH-CONCEPTS-001`

## Контекст

Сейчас `plan_score` и `branch_weak` показывают ложное проседание `coverage = 0.6` для веток `G-005` плана `doc-store`.

Механический gate зелёный:

```text
plan_validate: green
references: 1.0
embedding.available: true
embedding.state: ready
```

Но semantic score остаётся красным:

```text
coverage: 0.6
```

Расследование исходников показало причину.

Текущий алгоритм:

```python
def required_concepts(branch, concept_rows):
    slice_labels = {p.label for p in branch.hrs_slice if p.label is not None}
    required = set()
    for concept_id, _definition, source_labels in concept_rows:
        stripped = {label[1:-1] for label in source_labels}
        if stripped & slice_labels:
            required.add(concept_id)
    return required
```

`branch.hrs_slice` строится по `GS.fields["source_labels"]`.

В результате любой AS внутри GS наследует все concepts, которые имеют пересечение с `source_labels` глобального шага, даже если эти concepts относятся к более широкому системному контексту, а не к области ответственности текущего TS/AS.

Пример на `doc-store / G-005`:

```text
G-005.source_labels:
{x9y0}
{z1a2}
{b3d4}
{j5k6}
{e5f6}
```

По этим labels алгоритм считает required:

```text
C-017 QueryLanguage
C-013 PostgreSQLStorage
C-008 CanonicalDocumentTree
C-004 ServerAPI
C-001 DocStoreSystem
```

Но реальная область ответственности `G-005`:

```text
C-017 QueryLanguage
C-013 PostgreSQLStorage
C-008 CanonicalDocumentTree
```

Итог:

```text
declared = 3
required = 5
coverage = 3 / 5 = 0.6
```

Это ложное снижение оценки. `C-001 DocStoreSystem` и `C-004 ServerAPI` попали в required только потому, что используют общие HRS labels `{e5f6}` и `{b3d4}`.

## Проблема

Алгоритм `required_concepts()` смешивает:

1. HRS label traceability;
2. semantic scope текущего GS/TS/AS;
3. broad/system-level concepts;
4. branch-level responsibility.

Из-за этого branch coverage становится не scope-aware.

Текущий estimator отвечает на вопрос:

```text
Какие concepts вообще имеют source_labels, пересекающиеся с GS.source_labels?
```

А должен отвечать на вопрос:

```text
Какие concepts обязан покрыть именно этот branch: GS -> TS -> AS?
```

## Требование

Изменить алгоритм semantic coverage так, чтобы он учитывал область ответственности текущей ветки, а не только пересечение HRS labels.

Никаких обходов через искусственное добавление broad concepts в шаги делать нельзя.

## Новая логика

### 1. Ввести scope-aware required concepts

Для branch-level scoring required concepts должны вычисляться из иерархии:

```text
GS scope -> TS scope -> AS scope
```

А не напрямую из всех concepts по `GS.source_labels`.

Предлагаемая модель:

```text
GS required concepts:
  concepts, явно declared на GS,
  плюс валидируемые concepts, выведенные из GS.source_labels.

TS required concepts:
  intersection(parent GS scope, TS concepts)
  либо TS concepts, если они явно заданы.

AS required concepts:
  intersection(parent TS scope, AS concepts)
  либо AS concepts, если они явно заданы.
```

Для оценки конкретного AS branch:

```text
required = effective AS scope
declared = declared concepts on GS ∪ TS ∪ AS
coverage = len(required ∩ declared) / len(required)
```

Если AS явно declares concepts, то именно они являются его минимальной областью ответственности.

Если AS concepts пусты, допускается fallback к TS concepts.

Если TS concepts пусты, допускается fallback к GS concepts.

Но нельзя автоматически требовать от каждого AS все concepts, найденные через `GS.source_labels`.

### 2. Broad concepts не должны автоматически попадать в каждый AS

Concepts типа:

```text
DocStoreSystem
ServerAPI
```

могут быть релевантны плану или GS в целом, но не должны становиться обязательными для каждого AS, если они не объявлены в scope самого GS/TS/AS или не требуются явной relation/dependency логикой.

### 3. Source labels должны использоваться как traceability, а не как единственный источник branch responsibility

`source_labels` нужны для проверки трассировки HRS -> MRS -> steps.

Но semantic coverage branch должен использовать semantic scope, а не raw label expansion.

## Предлагаемые изменения в коде

Файл:

```text
plan_manager/scoring/estimators.py
```

Заменить текущую функцию:

```python
def required_concepts(branch: Branch, concept_rows) -> set[str]:
    ...
```

на scope-aware вариант.

Примерная структура:

```python
def branch_scope_concepts(branch: Branch) -> set[str]:
    gs_scope = set(branch.gs.concepts)
    ts_scope = set(branch.ts.concepts)
    as_scope = set(branch.atomic.concepts)

    if as_scope:
        return as_scope
    if ts_scope:
        return ts_scope
    if gs_scope:
        return gs_scope
    return set()
```

Затем:

```python
def required_concepts(branch: Branch, concept_rows) -> set[str]:
    scoped = branch_scope_concepts(branch)
    if scoped:
        return scoped

    # fallback только для старых/неполных планов
    return concepts_from_hrs_slice(branch, concept_rows)
```

Если нужен более строгий вариант:

```python
def required_concepts(branch: Branch, concept_rows) -> set[str]:
    hrs_required = concepts_from_hrs_slice(branch, concept_rows)
    scoped = branch_scope_concepts(branch)

    if scoped:
        return scoped & hrs_required or scoped

    return hrs_required
```

Важно: fallback по HRS labels должен быть именно fallback, а не основной механизм для AS scoring.

## Диагностика

Сейчас `verbose=true` недостаточен.

Добавить в `BranchScore` или отдельный diagnostics block:

```text
coverage.required_concepts
coverage.declared_concepts
coverage.missing_concepts
coverage.extra_declared_concepts
coverage.source_labels_used
coverage.scope_source
coverage.formula
```

Пример:

```json
{
  "coverage": {
    "value": 0.6,
    "required_concepts": ["C-001", "C-004", "C-008", "C-013", "C-017"],
    "declared_concepts": ["C-008", "C-013", "C-017"],
    "missing_concepts": ["C-001", "C-004"],
    "scope_source": "legacy_gs_source_labels",
    "formula": "3 / 5"
  }
}
```

После исправления для `G-005/T-002/A-002` ожидаемо:

```json
{
  "coverage": {
    "value": 1.0,
    "required_concepts": ["C-008", "C-013", "C-017"],
    "declared_concepts": ["C-008", "C-013", "C-017"],
    "missing_concepts": [],
    "scope_source": "as_or_ts_declared_scope",
    "formula": "3 / 3"
  }
}
```

## Команды, которых касается изменение

```text
plan_score
branch_weak
plan_status, если он использует SemanticIndex
```

## Acceptance criteria

1. Для плана `doc-store` ветки `G-005` не требуют `C-001 DocStoreSystem` и `C-004 ServerAPI`, если эти concepts не входят в declared scope конкретной GS/TS/AS ветки.

2. `coverage` для `G-005/T-002/A-002`, `G-005/T-002/A-003`, `G-005/T-001/A-001` перестаёт быть искусственно зафиксированным на `0.6`.

3. `verbose=true` для `plan_score` возвращает разбор coverage:

   * required concepts;
   * declared concepts;
   * missing concepts;
   * source labels;
   * выбранный источник scope;
   * формулу расчёта.

4. `plan_validate` остаётся механическим gate и не меняет свою семантику.

5. HRS label coverage остаётся отдельной проверкой traceability и не подменяет branch responsibility.

6. Старые планы без concepts на TS/AS продолжают работать через fallback на legacy label-based behavior, но в diagnostics явно видно:

```text
scope_source: legacy_gs_source_labels
```

7. Тест должен воспроизводить текущий кейс:

```text
GS.source_labels -> 5 concepts
GS/TS/AS declared -> 3 concepts
current coverage -> 0.6
new scope-aware coverage -> 1.0
```

## Тестовый сценарий

Добавить unit/integration test:

```text
tests/test_scoring_scope_aware_coverage.py
```

Проверить:

```text
- concept C-001 имеет source_label e5f6
- concept C-013 имеет source_label e5f6
- GS содержит source_label e5f6
- branch declares только C-013
- legacy required по labels дал бы C-001 + C-013
- новый required для AS branch даёт только C-013
- coverage = 1.0
- diagnostics показывает, что C-001 не считается missing
```

## Итог

Нужно исправить не план, а алгоритм SemanticIndex coverage.

Текущая формула допустима только как legacy fallback. Основной режим branch scoring должен быть scope-aware и обязан считать ответственность конкретной ветки, а не все concepts, случайно связанные с HRS labels глобального шага.
---
# CHANGE REQUEST: исправить алгоритм semantic coverage в `planmgr`

## ID

`CR-PLANMGR-BRANCH-COVERAGE-SCOPE-AWARE-001`

## Связанный баг

`BUG-PLANMGR-COVERAGE-ESTIMATOR-USES-GS-LABELS-TO-OVERREQUIRE-BRANCH-CONCEPTS-001`

## Контекст

Сейчас `plan_score` и `branch_weak` показывают ложное проседание `coverage = 0.6` для веток `G-005` плана `doc-store`.

Механический gate зелёный:

```text
plan_validate: green
references: 1.0
embedding.available: true
embedding.state: ready
```

Но semantic score остаётся красным:

```text
coverage: 0.6
```

Расследование исходников показало причину.

Текущий алгоритм:

```python
def required_concepts(branch, concept_rows):
    slice_labels = {p.label for p in branch.hrs_slice if p.label is not None}
    required = set()
    for concept_id, _definition, source_labels in concept_rows:
        stripped = {label[1:-1] for label in source_labels}
        if stripped & slice_labels:
            required.add(concept_id)
    return required
```

`branch.hrs_slice` строится по `GS.fields["source_labels"]`.

В результате любой AS внутри GS наследует все concepts, которые имеют пересечение с `source_labels` глобального шага, даже если эти concepts относятся к более широкому системному контексту, а не к области ответственности текущего TS/AS.

Пример на `doc-store / G-005`:

```text
G-005.source_labels:
{x9y0}
{z1a2}
{b3d4}
{j5k6}
{e5f6}
```

По этим labels алгоритм считает required:

```text
C-017 QueryLanguage
C-013 PostgreSQLStorage
C-008 CanonicalDocumentTree
C-004 ServerAPI
C-001 DocStoreSystem
```

Но реальная область ответственности `G-005`:

```text
C-017 QueryLanguage
C-013 PostgreSQLStorage
C-008 CanonicalDocumentTree
```

Итог:

```text
declared = 3
required = 5
coverage = 3 / 5 = 0.6
```

Это ложное снижение оценки. `C-001 DocStoreSystem` и `C-004 ServerAPI` попали в required только потому, что используют общие HRS labels `{e5f6}` и `{b3d4}`.

## Проблема

Алгоритм `required_concepts()` смешивает:

1. HRS label traceability;
2. semantic scope текущего GS/TS/AS;
3. broad/system-level concepts;
4. branch-level responsibility.

Из-за этого branch coverage становится не scope-aware.

Текущий estimator отвечает на вопрос:

```text
Какие concepts вообще имеют source_labels, пересекающиеся с GS.source_labels?
```

А должен отвечать на вопрос:

```text
Какие concepts обязан покрыть именно этот branch: GS -> TS -> AS?
```

## Требование

Изменить алгоритм semantic coverage так, чтобы он учитывал область ответственности текущей ветки, а не только пересечение HRS labels.

Никаких обходов через искусственное добавление broad concepts в шаги делать нельзя.

## Новая логика

### 1. Ввести scope-aware required concepts

Для branch-level scoring required concepts должны вычисляться из иерархии:

```text
GS scope -> TS scope -> AS scope
```

А не напрямую из всех concepts по `GS.source_labels`.

Предлагаемая модель:

```text
GS required concepts:
  concepts, явно declared на GS,
  плюс валидируемые concepts, выведенные из GS.source_labels.

TS required concepts:
  intersection(parent GS scope, TS concepts)
  либо TS concepts, если они явно заданы.

AS required concepts:
  intersection(parent TS scope, AS concepts)
  либо AS concepts, если они явно заданы.
```

Для оценки конкретного AS branch:

```text
required = effective AS scope
declared = declared concepts on GS ∪ TS ∪ AS
coverage = len(required ∩ declared) / len(required)
```

Если AS явно declares concepts, то именно они являются его минимальной областью ответственности.

Если AS concepts пусты, допускается fallback к TS concepts.

Если TS concepts пусты, допускается fallback к GS concepts.

Но нельзя автоматически требовать от каждого AS все concepts, найденные через `GS.source_labels`.

### 2. Broad concepts не должны автоматически попадать в каждый AS

Concepts типа:

```text
DocStoreSystem
ServerAPI
```

могут быть релевантны плану или GS в целом, но не должны становиться обязательными для каждого AS, если они не объявлены в scope самого GS/TS/AS или не требуются явной relation/dependency логикой.

### 3. Source labels должны использоваться как traceability, а не как единственный источник branch responsibility

`source_labels` нужны для проверки трассировки HRS -> MRS -> steps.

Но semantic coverage branch должен использовать semantic scope, а не raw label expansion.

## Предлагаемые изменения в коде

Файл:

```text
plan_manager/scoring/estimators.py
```

Заменить текущую функцию:

```python
def required_concepts(branch: Branch, concept_rows) -> set[str]:
    ...
```

на scope-aware вариант.

Примерная структура:

```python
def branch_scope_concepts(branch: Branch) -> set[str]:
    gs_scope = set(branch.gs.concepts)
    ts_scope = set(branch.ts.concepts)
    as_scope = set(branch.atomic.concepts)

    if as_scope:
        return as_scope
    if ts_scope:
        return ts_scope
    if gs_scope:
        return gs_scope
    return set()
```

Затем:

```python
def required_concepts(branch: Branch, concept_rows) -> set[str]:
    scoped = branch_scope_concepts(branch)
    if scoped:
        return scoped

    # fallback только для старых/неполных планов
    return concepts_from_hrs_slice(branch, concept_rows)
```

Если нужен более строгий вариант:

```python
def required_concepts(branch: Branch, concept_rows) -> set[str]:
    hrs_required = concepts_from_hrs_slice(branch, concept_rows)
    scoped = branch_scope_concepts(branch)

    if scoped:
        return scoped & hrs_required or scoped

    return hrs_required
```

Важно: fallback по HRS labels должен быть именно fallback, а не основной механизм для AS scoring.

## Диагностика

Сейчас `verbose=true` недостаточен.

Добавить в `BranchScore` или отдельный diagnostics block:

```text
coverage.required_concepts
coverage.declared_concepts
coverage.missing_concepts
coverage.extra_declared_concepts
coverage.source_labels_used
coverage.scope_source
coverage.formula
```

Пример:

```json
{
  "coverage": {
    "value": 0.6,
    "required_concepts": ["C-001", "C-004", "C-008", "C-013", "C-017"],
    "declared_concepts": ["C-008", "C-013", "C-017"],
    "missing_concepts": ["C-001", "C-004"],
    "scope_source": "legacy_gs_source_labels",
    "formula": "3 / 5"
  }
}
```

После исправления для `G-005/T-002/A-002` ожидаемо:

```json
{
  "coverage": {
    "value": 1.0,
    "required_concepts": ["C-008", "C-013", "C-017"],
    "declared_concepts": ["C-008", "C-013", "C-017"],
    "missing_concepts": [],
    "scope_source": "as_or_ts_declared_scope",
    "formula": "3 / 3"
  }
}
```

## Команды, которых касается изменение

```text
plan_score
branch_weak
plan_status, если он использует SemanticIndex
```

## Acceptance criteria

1. Для плана `doc-store` ветки `G-005` не требуют `C-001 DocStoreSystem` и `C-004 ServerAPI`, если эти concepts не входят в declared scope конкретной GS/TS/AS ветки.

2. `coverage` для `G-005/T-002/A-002`, `G-005/T-002/A-003`, `G-005/T-001/A-001` перестаёт быть искусственно зафиксированным на `0.6`.

3. `verbose=true` для `plan_score` возвращает разбор coverage:

   * required concepts;
   * declared concepts;
   * missing concepts;
   * source labels;
   * выбранный источник scope;
   * формулу расчёта.

4. `plan_validate` остаётся механическим gate и не меняет свою семантику.

5. HRS label coverage остаётся отдельной проверкой traceability и не подменяет branch responsibility.

6. Старые планы без concepts на TS/AS продолжают работать через fallback на legacy label-based behavior, но в diagnostics явно видно:

```text
scope_source: legacy_gs_source_labels
```

7. Тест должен воспроизводить текущий кейс:

```text
GS.source_labels -> 5 concepts
GS/TS/AS declared -> 3 concepts
current coverage -> 0.6
new scope-aware coverage -> 1.0
```

## Тестовый сценарий

Добавить unit/integration test:

```text
tests/test_scoring_scope_aware_coverage.py
```

Проверить:

```text
- concept C-001 имеет source_label e5f6
- concept C-013 имеет source_label e5f6
- GS содержит source_label e5f6
- branch declares только C-013
- legacy required по labels дал бы C-001 + C-013
- новый required для AS branch даёт только C-013
- coverage = 1.0
- diagnostics показывает, что C-001 не считается missing
```

## Итог

Нужно исправить не план, а алгоритм SemanticIndex coverage.

Текущая формула допустима только как legacy fallback. Основной режим branch scoring должен быть scope-aware и обязан считать ответственность конкретной ветки, а не все concepts, случайно связанные с HRS labels глобального шага.
---
# CHANGE REQUEST: исправить алгоритм semantic coverage в `planmgr`

## ID

`CR-PLANMGR-BRANCH-COVERAGE-SCOPE-AWARE-001`

## Связанный баг

`BUG-PLANMGR-COVERAGE-ESTIMATOR-USES-GS-LABELS-TO-OVERREQUIRE-BRANCH-CONCEPTS-001`

## Контекст

Сейчас `plan_score` и `branch_weak` показывают ложное проседание `coverage = 0.6` для веток `G-005` плана `doc-store`.

Механический gate зелёный:

```text
plan_validate: green
references: 1.0
embedding.available: true
embedding.state: ready
```

Но semantic score остаётся красным:

```text
coverage: 0.6
```

Расследование исходников показало причину.

Текущий алгоритм:

```python
def required_concepts(branch, concept_rows):
    slice_labels = {p.label for p in branch.hrs_slice if p.label is not None}
    required = set()
    for concept_id, _definition, source_labels in concept_rows:
        stripped = {label[1:-1] for label in source_labels}
        if stripped & slice_labels:
            required.add(concept_id)
    return required
```

`branch.hrs_slice` строится по `GS.fields["source_labels"]`.

В результате любой AS внутри GS наследует все concepts, которые имеют пересечение с `source_labels` глобального шага, даже если эти concepts относятся к более широкому системному контексту, а не к области ответственности текущего TS/AS.

Пример на `doc-store / G-005`:

```text
G-005.source_labels:
{x9y0}
{z1a2}
{b3d4}
{j5k6}
{e5f6}
```

По этим labels алгоритм считает required:

```text
C-017 QueryLanguage
C-013 PostgreSQLStorage
C-008 CanonicalDocumentTree
C-004 ServerAPI
C-001 DocStoreSystem
```

Но реальная область ответственности `G-005`:

```text
C-017 QueryLanguage
C-013 PostgreSQLStorage
C-008 CanonicalDocumentTree
```

Итог:

```text
declared = 3
required = 5
coverage = 3 / 5 = 0.6
```

Это ложное снижение оценки. `C-001 DocStoreSystem` и `C-004 ServerAPI` попали в required только потому, что используют общие HRS labels `{e5f6}` и `{b3d4}`.

## Проблема

Алгоритм `required_concepts()` смешивает:

1. HRS label traceability;
2. semantic scope текущего GS/TS/AS;
3. broad/system-level concepts;
4. branch-level responsibility.

Из-за этого branch coverage становится не scope-aware.

Текущий estimator отвечает на вопрос:

```text
Какие concepts вообще имеют source_labels, пересекающиеся с GS.source_labels?
```

А должен отвечать на вопрос:

```text
Какие concepts обязан покрыть именно этот branch: GS -> TS -> AS?
```

## Требование

Изменить алгоритм semantic coverage так, чтобы он учитывал область ответственности текущей ветки, а не только пересечение HRS labels.

Никаких обходов через искусственное добавление broad concepts в шаги делать нельзя.

## Новая логика

### 1. Ввести scope-aware required concepts

Для branch-level scoring required concepts должны вычисляться из иерархии:

```text
GS scope -> TS scope -> AS scope
```

А не напрямую из всех concepts по `GS.source_labels`.

Предлагаемая модель:

```text
GS required concepts:
  concepts, явно declared на GS,
  плюс валидируемые concepts, выведенные из GS.source_labels.

TS required concepts:
  intersection(parent GS scope, TS concepts)
  либо TS concepts, если они явно заданы.

AS required concepts:
  intersection(parent TS scope, AS concepts)
  либо AS concepts, если они явно заданы.
```

Для оценки конкретного AS branch:

```text
required = effective AS scope
declared = declared concepts on GS ∪ TS ∪ AS
coverage = len(required ∩ declared) / len(required)
```

Если AS явно declares concepts, то именно они являются его минимальной областью ответственности.

Если AS concepts пусты, допускается fallback к TS concepts.

Если TS concepts пусты, допускается fallback к GS concepts.

Но нельзя автоматически требовать от каждого AS все concepts, найденные через `GS.source_labels`.

### 2. Broad concepts не должны автоматически попадать в каждый AS

Concepts типа:

```text
DocStoreSystem
ServerAPI
```

могут быть релевантны плану или GS в целом, но не должны становиться обязательными для каждого AS, если они не объявлены в scope самого GS/TS/AS или не требуются явной relation/dependency логикой.

### 3. Source labels должны использоваться как traceability, а не как единственный источник branch responsibility

`source_labels` нужны для проверки трассировки HRS -> MRS -> steps.

Но semantic coverage branch должен использовать semantic scope, а не raw label expansion.

## Предлагаемые изменения в коде

Файл:

```text
plan_manager/scoring/estimators.py
```

Заменить текущую функцию:

```python
def required_concepts(branch: Branch, concept_rows) -> set[str]:
    ...
```

на scope-aware вариант.

Примерная структура:

```python
def branch_scope_concepts(branch: Branch) -> set[str]:
    gs_scope = set(branch.gs.concepts)
    ts_scope = set(branch.ts.concepts)
    as_scope = set(branch.atomic.concepts)

    if as_scope:
        return as_scope
    if ts_scope:
        return ts_scope
    if gs_scope:
        return gs_scope
    return set()
```

Затем:

```python
def required_concepts(branch: Branch, concept_rows) -> set[str]:
    scoped = branch_scope_concepts(branch)
    if scoped:
        return scoped

    # fallback только для старых/неполных планов
    return concepts_from_hrs_slice(branch, concept_rows)
```

Если нужен более строгий вариант:

```python
def required_concepts(branch: Branch, concept_rows) -> set[str]:
    hrs_required = concepts_from_hrs_slice(branch, concept_rows)
    scoped = branch_scope_concepts(branch)

    if scoped:
        return scoped & hrs_required or scoped

    return hrs_required
```

Важно: fallback по HRS labels должен быть именно fallback, а не основной механизм для AS scoring.

## Диагностика

Сейчас `verbose=true` недостаточен.

Добавить в `BranchScore` или отдельный diagnostics block:

```text
coverage.required_concepts
coverage.declared_concepts
coverage.missing_concepts
coverage.extra_declared_concepts
coverage.source_labels_used
coverage.scope_source
coverage.formula
```

Пример:

```json
{
  "coverage": {
    "value": 0.6,
    "required_concepts": ["C-001", "C-004", "C-008", "C-013", "C-017"],
    "declared_concepts": ["C-008", "C-013", "C-017"],
    "missing_concepts": ["C-001", "C-004"],
    "scope_source": "legacy_gs_source_labels",
    "formula": "3 / 5"
  }
}
```

После исправления для `G-005/T-002/A-002` ожидаемо:

```json
{
  "coverage": {
    "value": 1.0,
    "required_concepts": ["C-008", "C-013", "C-017"],
    "declared_concepts": ["C-008", "C-013", "C-017"],
    "missing_concepts": [],
    "scope_source": "as_or_ts_declared_scope",
    "formula": "3 / 3"
  }
}
```

## Команды, которых касается изменение

```text
plan_score
branch_weak
plan_status, если он использует SemanticIndex
```

## Acceptance criteria

1. Для плана `doc-store` ветки `G-005` не требуют `C-001 DocStoreSystem` и `C-004 ServerAPI`, если эти concepts не входят в declared scope конкретной GS/TS/AS ветки.

2. `coverage` для `G-005/T-002/A-002`, `G-005/T-002/A-003`, `G-005/T-001/A-001` перестаёт быть искусственно зафиксированным на `0.6`.

3. `verbose=true` для `plan_score` возвращает разбор coverage:

   * required concepts;
   * declared concepts;
   * missing concepts;
   * source labels;
   * выбранный источник scope;
   * формулу расчёта.

4. `plan_validate` остаётся механическим gate и не меняет свою семантику.

5. HRS label coverage остаётся отдельной проверкой traceability и не подменяет branch responsibility.

6. Старые планы без concepts на TS/AS продолжают работать через fallback на legacy label-based behavior, но в diagnostics явно видно:

```text
scope_source: legacy_gs_source_labels
```

7. Тест должен воспроизводить текущий кейс:

```text
GS.source_labels -> 5 concepts
GS/TS/AS declared -> 3 concepts
current coverage -> 0.6
new scope-aware coverage -> 1.0
```

## Тестовый сценарий

Добавить unit/integration test:

```text
tests/test_scoring_scope_aware_coverage.py
```

Проверить:

```text
- concept C-001 имеет source_label e5f6
- concept C-013 имеет source_label e5f6
- GS содержит source_label e5f6
- branch declares только C-013
- legacy required по labels дал бы C-001 + C-013
- новый required для AS branch даёт только C-013
- coverage = 1.0
- diagnostics показывает, что C-001 не считается missing
```

## Итог

Нужно исправить не план, а алгоритм SemanticIndex coverage.

Текущая формула допустима только как legacy fallback. Основной режим branch scoring должен быть scope-aware и обязан считать ответственность конкретной ветки, а не все concepts, случайно связанные с HRS labels глобального шага.
