# fiftybox-local 서빙 중인 모델 레인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `fiftybox-local`이 맥스튜디오와 ioh(R9700)에서 지금 서빙 중인 후보 모델을 시작할 때마다 찾아 PC마다 하나씩 레인으로 쓰게 한다.

**Architecture:** `fbl_task.py`의 `EXECUTORS` 표를 «후보 표»로 넓히고(`host`, `params_b` 필드), 고정 `LANE_POOL`을 없앤다. 후보 자격(표 + Pi 등록 + 설정 on)은 순수 함수가 가르고, 서빙 여부는 `executor_serving`이 가른다(맥스튜디오는 모델 ID까지, ioh는 HTTP 200만). `live_lanes`가 PC마다 `params_b`가 가장 큰 후보 하나만 남긴다. 풀·이동·메트릭 코드는 레인 이름이 후보 이름일 뿐이라 그대로 쓴다.

**Tech Stack:** Python 3 표준 라이브러리만(`fbl_task.py`는 NAS·Codex의 옛 Python에서도 돈다), `unittest`, bash 문서 테스트.

**Spec:** `docs/superpowers/specs/2026-10-29-fiftybox-local-served-model-lanes-design.md` (승인됨)

## Global Constraints

- 후보 표 값은 스펙 «후보 표» 그대로다: 맥스튜디오 8000·8001·11234·11235, ioh 8080·8083·8084. ioh 8081번(RTX 5060 Ti)은 표에 없다.
- 예산: Flash-Next 계열(`flash-next`, `iq3s`)은 70/140, 그 밖의 후보는 60/120. 다른 상수(`DESIGN_MD_MAX_LINES` 70, `TASK_SPEC_MAX_LINES` 15, `TASK_MAX_FILES` 2, `INTENT_SUMMARY_MAX_LINES` 14, `PROMPT_MAX_LINES` 140)와 `IMPL_TIMEOUT = 1800`은 바꾸지 않는다.
- 서버를 켜거나 끄지 않는다. 클라우드 모델은 후보가 아니다. 모든 디스패치는 `--provider`·`--model`을 후보 값으로 명시한다.
- `SKILL.md`는 230줄 이하다(`tests/test_local_skill_doc.sh`의 크기 가드). 지금 정확히 230줄이라 순증가가 0 이하여야 하고, 자세한 내용은 `reference.md`로 옮긴다.
- 코드 식별자·주석은 영어, 사용자에게 보이는 문구와 문서는 한국어(`AGENTS.md`).
- 산출물은 이 저장소 안에만 둔다. 예외는 마지막 Task의 실행용 사본 복사뿐이다.
- 작업 트리에 이 작업과 무관한 미커밋 수정이 이미 있다(`skills/fiftybox-local/` 4개 파일 + 테스트 2개: ioh 주소·컨텍스트 값 정정). 되돌리지 않는다.

## Review Focus

스펙이 암시하지만 정상 경로 테스트가 안 건드리는 입력들이다. 각 줄의 테스트는 맡는 Task에 들어 있다.

1. Pi `models.json`이 없거나 깨졌다 → 등록 확인만 건너뛰고 경고를 낸다. 레인이 0개가 되면 안 된다. (Task 1, 3)
2. `fiftybox-config.json`이 없거나 항목이 없다 → 켜짐으로 본다. `providers.pi.enabled`가 `false`면 전부 꺼짐이다. (Task 1)
3. 맥스튜디오 8000번이 후보와 다른 모델을 서빙한다 → 서빙 중이 아니다. 실행 중에 바뀌면 죽은 레인으로 보고 태스크가 이동한다. (Task 2, 4)
4. 한 PC에서 후보 둘이 동시에 응답한다 → 하나만 레인이 된다. 한 PC에 태스크 둘이 겹치지 않는다. (Task 2)
5. 후보가 하나도 남지 않는다 / 키가 필요한 포트가 401을 낸다 → 조용히 멈추지 않고 안내가 나온다. (Task 3)

## 파일 구조

- 수정 `skills/fiftybox-local/scripts/fbl_task.py` — 후보 표, 자격·서빙 판정, 선택, 배선. (한 파일에 이미 모여 있는 구조를 따른다. 쪼개지 않는다.)
- 만듦 `tests/test_fbl_served.py` — 새 동작 테스트. 수정 `tests/test_fbl_task.sh` — 이 파일을 실행 목록에 넣는다. 수정 `tests/test_fbl_pool.py` — `LANE_POOL`을 단언하는 테스트 교체, 프리플라이트 테스트 격리.
- 수정 `skills/fiftybox-local/SKILL.md`, `reference.md`, `agents/openai.yaml`, `tests/test_local_skill_doc.sh`.

새 테스트 파일은 다른 테스트처럼 `importlib`로 `fbl_task.py`를 경로로 불러온다(`tests/test_fbl_pool.py` 맨 위 `load_module()` 복사, 모듈 이름 `fbl_task_served`). 가짜 HTTP 서버는 `tests/test_fbl_task.py`의 `HealthTest`(253~290줄) 패턴을 쓴다.

---

### Task 1: 후보 표와 자격 판정

**Files:**
- Modify: `skills/fiftybox-local/scripts/fbl_task.py` (`Executor` 44~52줄, `EXECUTORS` 55~67줄, `LANE_POOL` 72줄 아래)
- Create: `tests/test_fbl_served.py`
- Modify: `tests/test_fbl_task.sh`

**Interfaces:**
- Produces: `Executor`에 키워드 필드 `host: str = ""`, `params_b: float = 0.0`(`prompt_max` 뒤).
- Produces: `EXECUTORS`(표 순서가 동점 규칙) — 아래 표. `HOST_ORDER = ("studio", "ioh")`.
- Produces: `PI_MODELS_PATH = Path("~/.pi/agent/models.json").expanduser()`, `CONFIG_PATH = Path("~/.claude/fiftybox-config.json").expanduser()`.
- Produces: `load_json(path: Path) -> dict | None` — 파일이 없거나 JSON이 깨졌으면 `None`.
- Produces: `eligible_candidates(registry: dict | None, config: dict | None) -> tuple[list[str], dict[str, str]]` — 자격 있는 이름(표 순서)과 `{이름: "not-in-pi" | "off-in-config"}`.
- `LANE_POOL`은 이 Task에서 남겨 둔다(Task 2에서 지운다).

| 이름 | host | provider / model | base_url | needs_key | 예산 | params_b |
|---|---|---|---|---|---|---|
| `flash-next` | studio | `macstudio-qwen-flash-next` / `Jundot--Qwen3.8-Flash-Next-oQ4e-mtp` | `http://100.115.199.115:8000` | True | 70/140 | 모델 카드 값(아래) |
| `qwen27b-mlx4` | studio | `macstudio-qwen-flash-next` / `lmstudio-community--Qwen3.8-27B-MLX-4bit` | `:8000` | True | 60/120 | 27 |
| `qwen27b-8bit` | studio | `macstudio-qwen38-27b` / `qwen38-27b-8bit` | `:11234` | False | 60/120 | 27 |
| `gemma4` | studio | `macstudio-gemma4` / `mlx-community--gemma-4-26B-A4B-it-qat-4bit` | `:11235` | False | 60/120 | 26 |
| `gpt-oss-20b` | studio | `macstudio-darkbloom` / `gpt-oss-20b` | `:8001` | False | 60/120 | 20 |
| `qwen35b-a3b` | studio | `macstudio-darkbloom` / `qwen3.5-35b-a3b` | `:8001` | False | 60/120 | 35 |
| `iq3s` | ioh | `ioh` / `qwen3.8-flash-next-iq3_s` | `http://100.76.6.16:8080` | False | 70/140 | `flash-next`와 같음 |
| `gemma31b` | ioh | `ioh-gemma31b` / `gemma-4-31b-it` | `:8083` | False | 60/120 | 31 |
| `qwen27b` | ioh | `ioh-qwen27b` / `qwen3.8-27b` | `:8084` | False | 60/120 | 27 |

(`:포트`는 같은 호스트 주소의 포트다. `flash-next`의 `params_b`는 모델 카드에서 찾아 넣는다. 찾지 못하면 `100.0`을 넣고 «estimate: 99GB oQ4e on disk» 주석을 단다. 테스트는 «다른 맥스튜디오 후보보다 크다»만 단언한다. `needs_key`가 False인 11234·8001은 서버가 떠 있을 때 `curl`로 한 번 확인한다. 401이면 True로 바꾼다.)

- [ ] **Step 1: 기준선을 기록한다**

Run: `bash tests/test_fbl_task.sh; bash tests/test_local_skill_doc.sh | tail -2; bash tests/test_install.sh >/dev/null; echo install=$?; bash tests/test_readme_commands.sh >/dev/null; echo readme=$?; bash tests/test_fbl_resume.sh >/dev/null; echo resume=$?`
Expected: `fbl_task.py unit tests`와 `lane-pool unit tests`가 PASS, 문서 테스트 `57 passed, 0 failed`. 나머지 세 줄의 종료 코드를 적어 둔다(Task 6에서 비교).

- [ ] **Step 2: 기존 미커밋 수정부터 정리한다**

`git diff --stat`으로 5개 파일의 기존 수정(ioh 주소 `100.76.6.16`, 컨텍스트 262,144)을 사용자에게 보여 준다. 사용자가 OK하면 이 수정만 먼저 `fix(fiftybox-local): ioh lane address and 262144 context`로 커밋한다. 사용자가 보류하면 이후 커밋에서 `git add -p`로 이 Task의 hunk만 담는다.

- [ ] **Step 3: 실패하는 테스트를 쓴다** — `tests/test_fbl_served.py`

```python
STUDIO = ["flash-next", "qwen27b-mlx4", "qwen27b-8bit", "gemma4", "gpt-oss-20b", "qwen35b-a3b"]
IOH = ["iq3s", "gemma31b", "qwen27b"]

def registry_of(*pairs):
    prov = {}
    for p, m in pairs:
        prov.setdefault(p, {"models": []})["models"].append({"id": m})
    return {"providers": prov}

def config_off(provider, model):
    return {"providers": {"pi": {"enabled": True,
            "backends": {provider: {"models": {model: False}}}}}}

class CandidateTableTest(unittest.TestCase):
    def test_names_order_and_hosts(self):
        self.assertEqual(list(fbl.EXECUTORS), STUDIO + IOH)
        self.assertEqual(fbl.HOST_ORDER, ("studio", "ioh"))
        self.assertEqual({n for n, e in fbl.EXECUTORS.items() if e.host == "ioh"}, set(IOH))

    def test_ioh_has_only_r9700_ports_and_never_8081(self):
        ports = {n: fbl.EXECUTORS[n].base_url.rsplit(":", 1)[1] for n in IOH}
        self.assertEqual(ports, {"iq3s": "8080", "gemma31b": "8083", "qwen27b": "8084"})
        self.assertFalse([n for n, e in fbl.EXECUTORS.items() if e.base_url.endswith(":8081")])

    def test_provider_and_model_are_explicit_and_never_the_cloud_default(self):
        for n, ex in fbl.EXECUTORS.items():
            self.assertTrue(ex.provider and ex.model, n)
            self.assertNotEqual(ex.provider, "opencode-go", n)

    def test_budgets_follow_the_model_family(self):
        for n, ex in fbl.EXECUTORS.items():
            want = (70, 140) if n in ("flash-next", "iq3s") else (60, 120)
            self.assertEqual((ex.design_max, ex.prompt_max), want, n)

    def test_params_decide_the_bigger_model(self):
        e = fbl.EXECUTORS
        self.assertTrue(all(e["flash-next"].params_b > e[n].params_b for n in STUDIO[1:]))
        self.assertEqual(e["iq3s"].params_b, e["flash-next"].params_b)
        self.assertGreater(e["gemma31b"].params_b, e["qwen27b"].params_b)
        self.assertGreater(e["qwen35b-a3b"].params_b, e["qwen27b-8bit"].params_b)
        self.assertEqual(e["qwen27b-mlx4"].params_b, e["qwen27b-8bit"].params_b)

    def test_only_omlx_8000_needs_the_key(self):
        self.assertEqual({n for n, e in fbl.EXECUTORS.items() if e.needs_key},
                         {"flash-next", "qwen27b-mlx4"})

class EligibleCandidatesTest(unittest.TestCase):
    def test_missing_registry_and_config_keep_everything(self):
        self.assertEqual(fbl.eligible_candidates(None, None), (list(fbl.EXECUTORS), {}))

    def test_unregistered_model_is_skipped_even_if_the_provider_exists(self):
        reg = registry_of(*[(e.provider, e.model) for n, e in fbl.EXECUTORS.items() if n != "qwen27b"],
                          ("ioh-qwen27b", "some-other-model"))
        names, skipped = fbl.eligible_candidates(reg, None)
        self.assertNotIn("qwen27b", names)
        self.assertEqual(skipped, {"qwen27b": "not-in-pi"})

    def test_config_off_drops_only_that_candidate(self):
        names, skipped = fbl.eligible_candidates(
            None, config_off("macstudio-qwen-flash-next", "lmstudio-community--Qwen3.8-27B-MLX-4bit"))
        self.assertIn("flash-next", names)
        self.assertEqual(skipped, {"qwen27b-mlx4": "off-in-config"})

    def test_config_without_an_entry_counts_as_on(self):
        names, skipped = fbl.eligible_candidates(None, {"providers": {"pi": {"enabled": True, "backends": {}}}})
        self.assertEqual((names, skipped), (list(fbl.EXECUTORS), {}))

    def test_pi_disabled_turns_every_candidate_off(self):
        names, skipped = fbl.eligible_candidates(None, {"providers": {"pi": {"enabled": False}}})
        self.assertEqual(names, [])
        self.assertEqual(set(skipped.values()), {"off-in-config"})

class LoadJsonTest(unittest.TestCase):
    def test_missing_broken_and_valid(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            (t / "bad.json").write_text("{nope", encoding="utf-8")
            (t / "ok.json").write_text('{"a": 1}', encoding="utf-8")
            self.assertIsNone(fbl.load_json(t / "missing.json"))
            self.assertIsNone(fbl.load_json(t / "bad.json"))
            self.assertEqual(fbl.load_json(t / "ok.json"), {"a": 1})
```

- [ ] **Step 4: 테스트가 실패하는지 본다**

Run: `python3 -I tests/test_fbl_served.py`
Expected: FAIL — `AttributeError: ... has no attribute 'host'` 등.

- [ ] **Step 5: 구현한다** — `Executor`에 두 필드를 더하고, `EXECUTORS`를 위 표대로 채우고(기존 `gemma4` 항목의 «Benchmark-only» 주석은 지운다), `HOST_ORDER`·경로 상수·`load_json`·`eligible_candidates`를 `LANE_POOL` 아래에 둔다. `eligible_candidates`의 규칙: `config`가 있고 `providers.pi.enabled`가 `False`면 전부 `off-in-config`. 아니면 후보마다 (1) `registry`가 `None`이 아니고 `registry["providers"][provider]["models"]`의 `id` 중에 `model`이 없으면 `not-in-pi`, (2) `config["providers"]["pi"]["backends"][provider]["models"][model]`이 `False`면 `off-in-config`. 항목이 없으면 켜짐이다.

- [ ] **Step 6: `tests/test_fbl_task.sh`에 새 파일을 넣는다** — `test_fbl_pool.py` 블록 바로 아래에 같은 모양으로 `python3 -I "$SCRIPT_DIR/tests/test_fbl_served.py"` 블록을 더한다(이름 `fbl_task.py served-model unit tests`).

- [ ] **Step 7: 통과를 확인한다**

Run: `bash tests/test_fbl_task.sh`
Expected: 세 블록 모두 PASS(기존 `test_fbl_pool.py`의 `LANE_POOL` 단언은 아직 그대로 통과한다).

- [ ] **Step 8: 커밋한다**

```bash
git add docs/superpowers/specs/2026-10-29-fiftybox-local-served-model-lanes-design.md plans/fiftybox-local-served-model-lanes-plan.md \
  skills/fiftybox-local/scripts/fbl_task.py tests/test_fbl_served.py tests/test_fbl_task.sh
git commit -m "feat(fiftybox-local): candidate table with hosts, params and eligibility" \
  -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 서빙 판정과 PC별 선택

**Files:**
- Modify: `skills/fiftybox-local/scripts/fbl_task.py` (`check_health`·`executor_health` 근처 376~391줄, `LANE_POOL` 72줄, `live_lanes` 484~490줄, `select_mode` 1152~1171줄)
- Modify: `tests/test_fbl_pool.py` (`LanePoolTableTest` 120~141줄)
- Test: `tests/test_fbl_served.py`

**Interfaces:**
- Consumes: Task 1의 `EXECUTORS`, `HOST_ORDER`, `Executor.host`/`params_b`.
- Produces: `fetch_models(base_url: str, key: str | None = None, timeout: float = 10) -> list[str]` — `GET {base_url}/v1/models`의 `data[].id`. HTTP 오류·연결 실패·JSON 오류는 모두 `[]`.
- Produces: `executor_models(ex: Executor) -> list[str]` — `needs_key`면 `KEY_FILE`의 키를 붙여 `fetch_models`.
- Produces: `executor_serving(ex: Executor) -> int` — `executor_health(ex)`가 200이고 `ex.host == "studio"`인데 `ex.model`이 `executor_models(ex)`에 없으면 `0`. 그 밖에는 `executor_health`의 코드 그대로. `executor_health`·`executor_models`는 모듈 전역으로 찾는다(테스트가 바꿔 끼운다).
- Produces: `live_lanes(names: list[str], health: Callable[[Executor], int]) -> list[str]` — 서명은 그대로. 알 수 없는 이름은 `ValueError`(지금과 같다). 200인 후보 중 PC(`host`)마다 `params_b`가 가장 큰 하나만 남기고(동점은 표 순서), 결과는 `HOST_ORDER` 순서다.
- Produces: `select_mode(lanes_arg, executor_arg, health, state, ids, *, candidates: list[str] | None = None) -> tuple[str, list[str]]` — `candidates=None`이면 `list(EXECUTORS)`. `--lanes` 이름은 먼저 `EXECUTORS`에 있는지 검사하고(없으면 `ValueError`), 그다음 `candidates`와 교집합을 낸다. 나머지 분기(single/pool/down)는 그대로.
- `LANE_POOL`은 이 Task에서 지운다.

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/test_fbl_served.py`에 추가

```python
def health_for(codes):
    return lambda ex: codes.get(ex.name, 0)

ALL = list(fbl.EXECUTORS)

class LiveLanesPerHostTest(unittest.TestCase):
    def test_todays_state_pairs_flash_next_with_gemma31b(self):
        up = health_for({"flash-next": 200, "gemma31b": 200})
        self.assertEqual(fbl.live_lanes(ALL, up), ["flash-next", "gemma31b"])

    def test_one_lane_per_pc_and_the_bigger_model_wins(self):
        up = health_for({"flash-next": 200, "gemma4": 200, "iq3s": 200, "gemma31b": 200})
        self.assertEqual(fbl.live_lanes(ALL, up), ["flash-next", "iq3s"])
        up = health_for({"gemma4": 200, "qwen35b-a3b": 200, "qwen27b-8bit": 200})
        self.assertEqual(fbl.live_lanes(ALL, up), ["qwen35b-a3b"])

    def test_equal_params_fall_back_to_table_order(self):
        up = health_for({"qwen27b-8bit": 200, "qwen27b-mlx4": 200})
        self.assertEqual(fbl.live_lanes(ALL, up), ["qwen27b-mlx4"])

    def test_a_new_r9700_model_becomes_the_ioh_lane_without_code_changes(self):
        self.assertEqual(fbl.live_lanes(ALL, health_for({"qwen27b": 200})), ["qwen27b"])

    def test_studio_comes_first_and_unknown_names_raise(self):
        up = health_for({"flash-next": 200, "iq3s": 200})
        self.assertEqual(fbl.live_lanes(["iq3s", "flash-next"], up), ["flash-next", "iq3s"])
        with self.assertRaises(ValueError):
            fbl.live_lanes(["nope"], up)

class ExecutorServingTest(unittest.TestCase):
    def setUp(self):
        self._h, self._m = fbl.executor_health, fbl.executor_models

    def tearDown(self):
        fbl.executor_health, fbl.executor_models = self._h, self._m

    def test_studio_candidate_needs_its_model_id_listed(self):
        fbl.executor_health = lambda ex: 200
        fbl.executor_models = lambda ex: ["Jundot--Qwen3.8-Flash-Next-oQ4e-mtp"]
        self.assertEqual(fbl.executor_serving(fbl.EXECUTORS["flash-next"]), 200)
        self.assertEqual(fbl.executor_serving(fbl.EXECUTORS["qwen27b-mlx4"]), 0)

    def test_ioh_candidate_only_needs_http_200(self):
        fbl.executor_health = lambda ex: 200
        fbl.executor_models = lambda ex: self.fail("ioh must not consult /v1/models ids")
        self.assertEqual(fbl.executor_serving(fbl.EXECUTORS["gemma31b"]), 200)

    def test_a_non_200_passes_through_without_listing_models(self):
        fbl.executor_health = lambda ex: 401
        fbl.executor_models = lambda ex: self.fail("no id check when health is not 200")
        self.assertEqual(fbl.executor_serving(fbl.EXECUTORS["flash-next"]), 401)

class SelectModeCandidatesTest(unittest.TestCase):
    def test_candidates_limit_the_pool(self):
        self.assertEqual(fbl.select_mode(None, None, lambda ex: 200, {}, [1], candidates=["iq3s"]),
                         ("single", ["iq3s"]))
        self.assertEqual(fbl.select_mode(None, None, lambda ex: 200, {}, [1], candidates=[]), ("down", []))

    def test_lanes_flag_is_intersected_with_candidates_and_still_validated(self):
        self.assertEqual(fbl.select_mode("flash-next,iq3s", None, lambda ex: 200, {}, [1],
                                         candidates=["iq3s"]), ("single", ["iq3s"]))
        with self.assertRaises(ValueError):
            fbl.select_mode("nope", None, lambda ex: 200, {}, [1], candidates=ALL)

    def test_todays_state_runs_as_a_two_lane_pool(self):
        up = health_for({"flash-next": 200, "gemma31b": 200})
        self.assertEqual(fbl.select_mode(None, None, up, {}, [1, 2]), ("pool", ["flash-next", "gemma31b"]))

class FetchModelsTest(unittest.TestCase):
    """Fake server as in HealthTest (tests/test_fbl_task.py:253-290)."""
    # 200 + {"data":[{"id":"a"},{"id":"b"}]} -> ["a", "b"]; the Authorization header is "Bearer k" when key="k".
    # 500, non-JSON body, JSON without "data", and a closed port each -> [].
```

`FetchModelsTest`의 주석 줄은 위 단언대로 테스트 메서드 네 개(`test_lists_ids`, `test_sends_bearer_key`, `test_errors_give_empty_list`, `test_unreachable_gives_empty_list`)로 채운다.

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -I tests/test_fbl_served.py`
Expected: FAIL — `fetch_models`, `executor_serving` 없음, `live_lanes`가 PC별로 거르지 않음.

- [ ] **Step 3: 구현한다** — 위 Interfaces의 함수들을 `check_health`/`executor_health` 근처(`fetch_models`, `executor_models`, `executor_serving`)와 기존 위치(`live_lanes`, `select_mode`)에 쓴다. `LANE_POOL` 정의와 `live_lanes`의 `LANE_POOL.index` 정렬을 지운다. `live_lanes` 독스트링은 «one lane per PC, bigger params_b wins, ties by table order, studio first»로 고친다.

- [ ] **Step 4: 낡은 단언을 교체한다** — `tests/test_fbl_pool.py`의 `LanePoolTableTest`에서 `test_lane_pool_is_studio_first_then_ioh`와 `test_gemma4_is_not_a_lane`를 지우고 아래로 바꾼다.

```python
    def test_there_is_no_fixed_pool_constant(self):
        self.assertFalse(hasattr(fbl, "LANE_POOL"))

    def test_gemma4_is_an_ordinary_studio_candidate(self):
        self.assertEqual(fbl.live_lanes(["gemma4"], lambda ex: 200), ["gemma4"])
```

- [ ] **Step 5: 통과를 확인한다**

Run: `bash tests/test_fbl_task.sh`
Expected: 세 블록 모두 PASS. (`SelectModeTest`의 `test_two_live_lanes_use_the_pool` 등 기존 풀 테스트는 그대로 통과해야 한다.) `_preflight_pool`이 아직 `LANE_POOL`을 쓰면 `NameError`가 나므로, 이 Task에서 `_preflight_pool`의 `LANE_POOL` 참조를 `list(EXECUTORS)`로 임시 대체해 컴파일만 유지한다(Task 3이 다시 쓴다).

- [ ] **Step 6: 커밋한다**

```bash
git add skills/fiftybox-local/scripts/fbl_task.py tests/test_fbl_served.py tests/test_fbl_pool.py
git commit -m "feat(fiftybox-local): pick one served model per PC, bigger params first" \
  -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 프리플라이트와 run 배선

**Files:**
- Modify: `skills/fiftybox-local/scripts/fbl_task.py` (`probe_lanes` 414~424줄, `_executor` 1144~1149줄, `_preflight_pool` 1200~1228줄, `cmd_run` 1265·1283~1290줄, `--lanes` 도움말 1354줄)
- Modify: `tests/test_fbl_pool.py` (`PreflightPoolTest` 919줄~)
- Test: `tests/test_fbl_served.py`

**Interfaces:**
- Consumes: Task 1 `load_json`·`eligible_candidates`·`PI_MODELS_PATH`·`CONFIG_PATH`, Task 2 `executor_serving`·`live_lanes`·`select_mode(candidates=)`.
- Produces: `current_candidates() -> tuple[list[str], dict[str, str], list[str]]` — `PI_MODELS_PATH`·`CONFIG_PATH`를 호출 시점의 모듈 전역에서 읽어 (자격 이름, 건너뛴 이유, 경고 문구)를 낸다. `models.json`을 못 읽으면 경고 `WARN=pi registry unreadable; registration check skipped`를 하나 담는다.
- 풀 프리플라이트 출력(순서대로): 경고 줄들, 후보마다 `SKIP=<이름> REASON=<이유>`, 자격 있는 후보마다 `LANE=<이름> HEALTH=<executor_health 코드>`(코드가 200이면 ` SERVED=yes|no`를 덧붙인다. `no`는 맥스튜디오 서버는 떴지만 후보 모델 ID가 목록에 없다는 뜻), `PICK=studio:flash-next,ioh:gemma31b`(`host:이름`, `HOST_ORDER` 순), 기존 `WARM=`, `LANES_UP=`, `PREFLIGHT=ok`.
- 자격 있는 후보가 0개면 `PREFLIGHT=none (every candidate is off in fiftybox-config or missing from Pi; run /fiftybox-config)`을 찍고 1을 돌려준다(아무 서버도 건드리지 않는다). 살아 있는 레인이 0개면 기존대로 `LANES=<probe_lanes()>`를 찍고, 자격 있는 맥스튜디오 후보 중 `executor_health`가 401인 것이 있으면 `PREFLIGHT=auth (...)`, 아니면 `PREFLIGHT=down (start procedure: reference.md)`.
- `cmd_run`: `--executor`가 없고 자격 있는 후보가 0개면 `STOP=NO_CANDIDATES DETAIL=every candidate is off in fiftybox-config or missing from Pi`를 찍고 2를 돌려준다. 그 밖에는 `select_mode(..., executor_serving, state, ids, candidates=...)`, 풀의 `LanePool(health=executor_serving)`, 감시견 `OrchestrateDispatcher(health=lambda: executor_serving(ex), ...)`, 단일 모드 `TaskRunner(..., health=executor_serving)`을 쓴다.
- `probe_lanes()`의 `lsof` 포트 목록에 `8001`을 더한다. `_executor`의 «not the skill default» `WARN=` 출력을 없앤다(`DEFAULT_EXECUTOR`는 남긴다). `--lanes` 도움말은 «comma-separated candidate names from EXECUTORS (default: every eligible candidate)».

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/test_fbl_served.py`에 추가

```python
class PreflightServedTest(unittest.TestCase):
    def setUp(self):
        self._saved = (fbl.executor_health, fbl.executor_models, fbl.warm_up, fbl.probe_lanes,
                       fbl.PI_MODELS_PATH, fbl.CONFIG_PATH)
        self.td = tempfile.TemporaryDirectory()
        t = Path(self.td.name)
        fbl.PI_MODELS_PATH, fbl.CONFIG_PATH = t / "pi.json", t / "config.json"  # missing files
        fbl.executor_models = lambda ex: [ex.model]
        fbl.warm_up = lambda ex: 200
        fbl.probe_lanes = lambda: "none"

    def tearDown(self):
        (fbl.executor_health, fbl.executor_models, fbl.warm_up, fbl.probe_lanes,
         fbl.PI_MODELS_PATH, fbl.CONFIG_PATH) = self._saved
        self.td.cleanup()

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fbl.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_todays_state_picks_flash_next_and_gemma31b(self):
        warmed = []
        fbl.executor_health = health_for({"flash-next": 200, "gemma31b": 200})
        fbl.warm_up = lambda ex: warmed.append(ex.name) or 200
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 0)
        for line in ("LANE=flash-next HEALTH=200 SERVED=yes", "LANE=gemma31b HEALTH=200",
                     "LANE=iq3s HEALTH=0", "PICK=studio:flash-next,ioh:gemma31b",
                     "LANES_UP=flash-next,gemma31b", "PREFLIGHT=ok"):
            self.assertIn(line, out)
        self.assertEqual(warmed, ["flash-next", "gemma31b"])

    def test_skipped_candidates_are_listed_and_not_probed(self):
        t = Path(self.td.name)
        (t / "pi.json").write_text(json.dumps(registry_of(
            *[(e.provider, e.model) for n, e in fbl.EXECUTORS.items() if n != "qwen27b"])), encoding="utf-8")
        (t / "config.json").write_text(json.dumps(config_off(
            "macstudio-qwen-flash-next", "lmstudio-community--Qwen3.8-27B-MLX-4bit")), encoding="utf-8")
        fbl.executor_health = health_for({"flash-next": 200})
        rc, out, _ = self.run_main("preflight")
        self.assertIn("SKIP=qwen27b REASON=not-in-pi", out)
        self.assertIn("SKIP=qwen27b-mlx4 REASON=off-in-config", out)
        self.assertNotIn("LANE=qwen27b ", out)
        self.assertNotIn("LANE=qwen27b-mlx4 ", out)

    def test_studio_up_but_model_not_listed_is_not_served(self):
        fbl.executor_health = health_for({n: 200 for n in STUDIO})
        fbl.executor_models = lambda ex: []
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 1)
        self.assertIn("LANE=flash-next HEALTH=200 SERVED=no", out)
        self.assertNotIn("PICK=", out)

    def test_no_eligible_candidate_stops_with_guidance(self):
        (Path(self.td.name) / "config.json").write_text(
            json.dumps({"providers": {"pi": {"enabled": False}}}), encoding="utf-8")
        fbl.executor_health = lambda ex: self.fail("no server may be touched")
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 1)
        self.assertIn("PREFLIGHT=none", out)
        self.assertIn("/fiftybox-config", out)

    def test_unreadable_registry_warns_and_checks_nothing(self):
        fbl.executor_health = health_for({"flash-next": 200})
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 0)
        self.assertIn("WARN=pi registry unreadable", out)

    def test_a_401_still_gives_the_auth_message(self):
        fbl.executor_health = health_for({"flash-next": 401})
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 1)
        self.assertIn("PREFLIGHT=auth", out)

    def test_explicit_executor_prints_no_benchmark_warning(self):
        fbl.executor_health = lambda ex: 200
        rc, _, err = self.run_main("preflight", "--executor", "gemma4")
        self.assertEqual(rc, 0)
        self.assertNotIn("WARN=", err)

    def test_run_without_candidates_stops_before_dispatch(self):
        (Path(self.td.name) / "config.json").write_text(
            json.dumps({"providers": {"pi": {"enabled": False}}}), encoding="utf-8")
        rc, out, _ = self.run_main("run", "--artifact-dir", self.td.name, "--tasks", "1")
        self.assertEqual(rc, 2)
        self.assertIn("STOP=NO_CANDIDATES", out)

class ProbeLanesTest(unittest.TestCase):
    def test_lsof_checks_the_darkbloom_port_too(self):
        seen = []
        real = fbl.subprocess.run
        fbl.subprocess.run = lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
        try:
            fbl.probe_lanes()
        finally:
            fbl.subprocess.run = real
        self.assertIn("-iTCP:8001", seen[0][-1])
```

- [ ] **Step 2: 기존 프리플라이트 테스트를 격리한다** — `tests/test_fbl_pool.py`의 `PreflightPoolTest.setUp`/`tearDown`에서, 실제 `~/.pi`·`~/.claude` 파일을 읽지 않도록 `fbl.PI_MODELS_PATH`·`fbl.CONFIG_PATH`를 임시 폴더의 없는 경로로, `fbl.executor_models`를 `lambda ex: [ex.model]`로 바꿔 끼우고 `tearDown`에서 되돌린다. 단언은 바꾸지 않는다(새 출력은 기존 부분 문자열을 모두 포함한다).

- [ ] **Step 3: 실패를 확인한다**

Run: `python3 -I tests/test_fbl_served.py PreflightServedTest ProbeLanesTest`
Expected: FAIL — `current_candidates` 없음, `PICK=` 없음 등.

- [ ] **Step 4: 구현한다** — 위 Interfaces대로 `current_candidates`, `_preflight_pool`, `cmd_run`, `probe_lanes`, `_executor`, 파서 도움말을 고친다. 워밍업 표시 파일 규칙(`flash-next`는 `warmed`, 나머지는 `warmed-<lane>`)은 그대로 둔다.

- [ ] **Step 5: 통과를 확인한다**

Run: `bash tests/test_fbl_task.sh`
Expected: 세 블록 모두 PASS.

- [ ] **Step 6: 커밋한다**

```bash
git add skills/fiftybox-local/scripts/fbl_task.py tests/test_fbl_served.py tests/test_fbl_pool.py
git commit -m "feat(fiftybox-local): discover served models in preflight and run" \
  -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 실행 중 모델이 바뀌면 죽은 레인으로 본다

**Files:**
- Modify: `skills/fiftybox-local/scripts/fbl_task.py` (`TaskRunner._run_one`, 857줄 `r.klass = classify_failure(out_text, exit_code, over_budget=False)` 바로 아래)
- Test: `tests/test_fbl_pool.py` (`LanePoolMovesTest`에 추가)

**Interfaces:**
- Consumes: Task 3에서 풀·단일 모드의 `health`가 `executor_serving`이 된다. `TaskRunner.health`는 `Callable[[Executor], int]`.
- Produces: `_run_one`이 분류 직후 `r.klass == "model"`이고 `self.health(self.ex) != 200`이면 `r.klass = "server"`로 바꾼다(레인이 그 모델 서빙을 멈춘 것은 인프라 문제이지 모델 실패가 아니다). 그러면 아래쪽 기존 코드가 그대로 일한다: 풀에서는 메트릭이 `moved` 행이 되고 재시도 예산을 쓰지 않으며, `LanePool.handle`이 `server`로 보고 태스크를 한 번 이동시킨다. `LanePool.handle`은 고치지 않는다. `model`인데 헬스가 200이면 지금처럼 `model`로 멈춘다.

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `LanePoolMovesTest`의 `test_dead_ioh_mid_task_moves_task_to_studio`(651줄)를 본떠서

```python
    def test_model_swapped_off_a_lane_moves_the_task(self):
        self.add_task(1, "calc1.py")
        self.add_task(2, "calc2.py")
        swapped = set()

        def hook(wt, task_text, ex):
            fname = spec_file(task_text)
            if ex.name == "iq3s":
                swapped.add("iq3s")  # from now on the server no longer serves this model
                (wt / fname).write_text("half-broken\n", encoding="utf-8")
                return 1
            (wt / fname).write_text(GOOD, encoding="utf-8")
            return 0

        pool = self.pool(["flash-next", "iq3s"], hook, log_tail="Unknown model: qwen3.8-flash-next-iq3_s",
                         health=lambda ex: 0 if ex.name in swapped else 200)
        by_task = {r.task: r for r in pool.run([1, 2])}
        self.assertEqual(by_task[2].verdict, "CLEAN", fbl.format_result(by_task[2]))
        self.assertEqual(by_task[2].moved, "iq3s->flash-next")
        state = json.loads((self.art / ".fbl" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tasks"]["2"]["attempts"], 1)
        metrics = (self.art / "executor-metrics.md").read_text(encoding="utf-8")
        self.assertIn("moved", metrics)  # infrastructure row, so calibrate ignores it

    def test_model_error_while_the_server_still_serves_it_stops(self):
        self.add_task(1, "calc1.py")

        def hook(wt, task_text, ex):
            return 1

        pool = self.pool(["flash-next"], hook, log_tail="Unknown model: typo")
        r = pool.run([1])[0]
        self.assertEqual(r.klass, "model")
        self.assertIsNone(r.moved)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -I tests/test_fbl_pool.py LanePoolMovesTest`
Expected: 첫 테스트 FAIL(태스크 2가 이동하지 않고 `model`로 멈추며 메트릭에 `moved`가 없다), 둘째는 PASS.

- [ ] **Step 3: 구현한다** — `_run_one`의 `classify_failure` 직후에 위 Interfaces의 재분류 한 블록(`if r.klass == "model" and self.health(self.ex) != 200: r.klass = "server"`, 한 줄 영어 주석)을 넣는다.

- [ ] **Step 4: 통과를 확인한다**

Run: `bash tests/test_fbl_task.sh`
Expected: 세 블록 모두 PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add skills/fiftybox-local/scripts/fbl_task.py tests/test_fbl_pool.py
git commit -m "fix(fiftybox-local): count a swapped model as a server failure, not a model failure" \
  -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 문서와 문서 테스트

**Files:**
- Modify: `skills/fiftybox-local/SKILL.md`, `skills/fiftybox-local/reference.md`, `skills/fiftybox-local/agents/openai.yaml`
- Modify: `tests/test_local_skill_doc.sh`

**Interfaces:**
- Consumes: Task 1~4의 동작(`PICK=`, `SKIP=`, `NO_CANDIDATES`, 후보 이름).
- Produces: 문서가 아래 문자열을 포함한다 — `SKILL.md`: `NO_CANDIDATES`, `PICK=`, `R9700`, `후보 표`, `iq3s`; `reference.md`: `macstudio-gemma4`, `ioh-gemma31b`, `ioh-qwen27b`, `8081`, `RTX 5060 Ti`, `레인 풀: ioh`(제목에 포함), `SKIP=`. 어느 문서에도 `LANE_POOL`과 `benchmark-only`가 없다.

- [ ] **Step 1: 문서 테스트를 먼저 바꾼다** — `tests/test_local_skill_doc.sh`:
  - 「gemma4 is a benchmark-only lane」 블록(`lacks "$SKILL" "macstudio-gemma4"`)을 지우고 아래로 바꾼다.
  - `reference.md`의 `has "$REF" "benchmark-only"` 줄을 지운다.
  - ioh 표 한 줄을 단언하던 줄(`| ioh | \`ioh\` / ...`)을 지운다.

```bash
# served-model lanes: candidates live in reference.md, SKILL.md stays compact
has "$REF" "macstudio-gemma4" "reference.md lists gemma4 as an ordinary Studio candidate"
has "$REF" "ioh-gemma31b" "reference.md lists the ioh Gemma-31B candidate"
has "$REF" "ioh-qwen27b" "reference.md lists the ioh Qwen3.8-27B candidate"
has "$REF" "RTX 5060 Ti" "reference.md says the 5060 Ti (8081) is not a lane"
has "$REF" "SKIP=" "reference.md documents the preflight SKIP= line"
has "$SKILL" "R9700" "SKILL.md limits ioh to the R9700"
has "$SKILL" "PICK=" "SKILL.md shows the preflight PICK= line"
has "$SKILL" "NO_CANDIDATES" "SKILL.md documents the NO_CANDIDATES stop"
has "$SKILL" "후보 표" "SKILL.md names the candidate table"
lacks "$SKILL" "benchmark-only" "SKILL.md has no benchmark-only lane"
lacks "$REF" "benchmark-only" "reference.md has no benchmark-only lane"
lacks "$SKILL" "LANE_POOL" "SKILL.md no longer mentions the fixed pool constant"
lacks "$REF" "LANE_POOL" "reference.md no longer mentions the fixed pool constant"
```

  Run: `bash tests/test_local_skill_doc.sh | grep FAIL`
  Expected: 새 `has`/`lacks` 줄들이 FAIL로 나온다(문서가 아직 옛 상태).

- [ ] **Step 2: `SKILL.md`를 고친다** (230줄 이하 유지). 스펙 «사용자가 정한 것»·«제 판단으로 정한 것»을 한국어로 옮긴다.
  - `description:`: «Mac Studio와 ioh(R9700)가 지금 서빙 중인 후보 모델 — 시작할 때 PC마다 하나씩, 둘 다 살아 있으면 독립 태스크 병렬, 하나면 순차, 후보 표 밖 모델 없음».
  - 첫 문단과 «레인 풀» 절: 고정 표 대신 후보 표 요약 두 줄(Studio / ioh(R9700만)) + 선택 규칙 한 줄(맥스튜디오는 모델 ID까지 확인하고 둘 이상이면 파라미터가 큰 쪽, ioh는 8080·8083·8084만, 8081번 5060 Ti는 레인이 아님). 전체 표는 `reference.md`를 가리킨다. `Jundot--Qwen3.8-Flash-Next-oQ4e-mtp`, `100.115.199.115:8000`, `macstudio-omlx.key`, `262,144`, `macstudio-qwen-flash-next`, `iq3s`는 SKILL.md에 남긴다(기존 문서 테스트가 단언한다).
  - 「스튜디오 백엔드」 단락은 `reference.md`로 옮기고 SKILL.md에는 링크 한 줄만 남긴다.
  - 실행 예산: 표 아래에 «Flash-Next 계열 70/140, 그 밖의 후보 60/120» 한 줄.
  - 설정 게이트: 꺼진 후보(`providers.pi.backends.<provider>.models.<model>`, 예: `providers.pi.backends.macstudio-qwen-flash-next`)는 풀에서 빠지고 항목이 없으면 켜짐, 후보가 0개일 때만 `NO_CANDIDATES`로 중단하고 `/fiftybox-config`를 안내.
  - Step 2: `preflight` 출력에 `PICK=`·`SKIP=`가 있다고 한 줄. STOP 사유 목록에 `NO_CANDIDATES`.
  - «실패 처리»·«안전 계약»의 «레인 표 밖» → «후보 표 밖». 클라우드/원격 전환 금지 문장은 그대로 둔다.
  - Step 2·Step 7의 `--provider macstudio-qwen-flash-next` 명령은 `grep -n "args.provider" skills/fiftybox-orchestration/scripts/orchestrate.py`로 `setup`·`deploy` 단계가 실제로 이 값으로 디스패치하는지 확인한 뒤, 하지 않으면 그대로 둔다(디스패치는 `fbl_task.py`가 후보 값으로 한다).

- [ ] **Step 3: `reference.md`를 고친다.** 후보 표 전체(이름·PC·provider/model·포트·키·예산·`params_b`), 선택 규칙, 「스튜디오 백엔드」 단락, `SKIP=`/`PICK=` 설명, 모델 교체 처리(실행 중 바뀌면 이동), Pi에 등록 안 된 모델 안내(예: `mix6`), ioh 8081번(RTX 5060 Ti)은 레인이 아님을 쓴다. 「benchmark-only: gemma4 레인」 절은 지운다. 제목 «레인 풀: ioh»는 유지(문서 테스트가 찾는다). 본문의 `LANE_POOL` 언급은 «후보 표(`EXECUTORS`)»로 바꾼다.

- [ ] **Step 4: `agents/openai.yaml`을 고친다.** `description`과 `default_prompt`를 «고정 executor» 대신 «PC가 서빙 중인 로컬 모델 레인 풀»로 바꾼다. 단어 `Flash-Next`는 남기고 `Gemma4-26B-A4B`는 넣지 않는다.

- [ ] **Step 5: 통과를 확인한다**

Run: `bash tests/test_local_skill_doc.sh | tail -3; wc -l skills/fiftybox-local/SKILL.md; grep -rn "LANE_POOL" --exclude-dir=.git --exclude-dir=.worktrees --exclude-dir=__pycache__ . | grep -v "docs/superpowers\|plans/"`
Expected: `Results: N passed, 0 failed`, 줄 수 230 이하, `grep`은 아무것도 출력하지 않는다.

- [ ] **Step 6: 커밋한다**

```bash
git add skills/fiftybox-local/SKILL.md skills/fiftybox-local/reference.md skills/fiftybox-local/agents/openai.yaml tests/test_local_skill_doc.sh
git commit -m "docs(fiftybox-local): describe the served-model candidate table" \
  -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 실행용 사본 동기화와 실서버 확인

**Files:**
- Copy: repo `skills/fiftybox-local/{SKILL.md,reference.md,scripts/fbl_task.py,agents/openai.yaml}` → `~/.claude/skills/fiftybox-local/`, `~/.codex/skills/fiftybox-local/`

**Interfaces:**
- Consumes: Task 1~5의 결과물.
- Produces: 두 실행용 사본이 repo와 같다. `~/.claude/skills/fiftybox-local/scripts/fbl_task.py`에 있던 손으로 넣은 `gemma31b` 항목(백업 `fbl_task.py.bak-gemma31b-20261029`)은 repo의 새 표가 대신한다.

- [ ] **Step 1: 전체 테스트를 돌리고 기준선과 비교한다**

Run: `bash tests/test_fbl_task.sh; bash tests/test_local_skill_doc.sh | tail -1; for t in test_install test_readme_commands test_fbl_resume; do bash tests/$t.sh >/dev/null; echo $t=$?; done`
Expected: 모두 PASS이고 세 종료 코드가 Task 1 Step 1에서 적어 둔 값과 같다.

- [ ] **Step 2: 실행용 사본에 복사한다** (`.bak-*` 백업 파일은 지우지 않는다)

```bash
S=skills/fiftybox-local
for D in ~/.claude/skills/fiftybox-local ~/.codex/skills/fiftybox-local; do
  cp $S/SKILL.md $S/reference.md "$D"/
  cp $S/scripts/fbl_task.py "$D"/scripts/
  cp $S/agents/openai.yaml "$D"/agents/
done
diff -rq $S ~/.claude/skills/fiftybox-local | grep -v "bak\|__pycache__"; diff -rq $S ~/.codex/skills/fiftybox-local | grep -v "bak\|__pycache__"
```
Expected: `diff`가 아무것도 출력하지 않는다.

- [ ] **Step 3: 실서버로 프리플라이트를 한 번 돌린다** (읽기 요청과 1토큰 워밍업만 보낸다)

Run: `python3 ~/.claude/skills/fiftybox-local/scripts/fbl_task.py preflight`
Expected(2026-10-29 상태 기준): `SKIP=qwen27b-mlx4 REASON=off-in-config`, `SKIP=gpt-oss-20b ...`, `SKIP=qwen35b-a3b ...`(설정에서 꺼져 있음), `LANE=flash-next HEALTH=200 SERVED=yes`, `LANE=gemma31b HEALTH=200`, `PICK=studio:flash-next,ioh:gemma31b`, `PREFLIGHT=ok`. 서버 상태가 달라졌으면 스펙 규칙에 맞는 출력이면 통과다(R9700에 다른 모델이 올라가 있으면 그 후보가 `PICK`에 나온다). 8081번 관련 줄이나 클라우드 provider가 나오면 실패다.

- [ ] **Step 4: 마무리를 보고한다.** `~/.claude/skills`는 별도 git 저장소이고 그 안의 `fiftybox-local`에 커밋 안 된 변경이 생겼다고 사용자에게 알린다. 그 저장소에서 커밋·푸시하지 않는다(사용자가 정한다). 이 저장소의 `git status`에 이 작업과 무관한 수정이 남아 있지 않은지 확인해 보고한다.

---

## 자체 검토 결과

- **스펙 범위:** 목표 1~6 → Task 2·3(발견·선택), Task 1(표·R9700 한정), Task 2(큰 모델), 메트릭은 레인 이름이 후보 이름이라 변경 없음(`calibrate_by_lane`은 임의 이름을 받는다). 비목표·반대 목표 → Task 1 테스트(8081 없음, provider 명시, 예산), Task 3(서버 조작 없음), Task 4(모델 교체). 성공 기준 8개는 Task 1~4 테스트와 Task 6 실서버 확인에 하나씩 대응한다.
- **타입 일관성:** `Executor.host`/`params_b`, `HOST_ORDER`, `load_json`, `eligible_candidates`, `fetch_models`, `executor_models`, `executor_serving`, `live_lanes`, `select_mode(candidates=)`, `current_candidates`는 Task 간 이름과 서명이 같다.
- **비율:** 스펙 109줄에 계획 637줄이다. 스펙의 몇 배라서 길다. 늘어난 부분은 거의 전부 테스트 단언 코드(Task 1~4)이고, 구현 본문은 하나도 쓰지 않았다. 테스트를 줄이려면 Task 3의 `PreflightServedTest` 단언을 문장으로 바꾸면 된다.
