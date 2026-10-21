# 프로젝트 하네스 조립

> 담는 것: git 과 원격 연결부터 언어 선택과 첫 코드의 분류와 검사 연결까지의 절차. 담지 않는 것: 그래프 승인 계약(→ [../COMPONENTS.md](../COMPONENTS.md)). 읽는 시점: 새 프로젝트를 시작하거나 기술 스택을 바꿀 때.

## git 과 원격

게이트는 `git ls-files` 로 대상을 모은다. git 저장소가 아니면 모든 게이트의 대상이 0개라 아무것도 검사하지 않는다.
원격이 없으면 커밋이 이 컴퓨터에만 남는다. 과업은 끝낼 수 있지만(`python -X utf8 -m kernel.task finish` 가 로컬에만 합친다) 백업이 없다.

| 상태 | 할 일 |
|:--|:--|
| 원류에서 막 clone 했다 | `python -X utf8 harness_install.py --new` — 어느 셸에서든 원류 이력을 지우고 새 이력과 첫 커밋을 만든다. git 사용자 정보가 없으면 아무것도 바꾸지 않고 설정 명령을 보인다 |
| git 저장소가 아니다 | `git init` 하고 첫 커밋을 만든다 |
| origin 이 있다 | 다음 절로 간다 |
| origin 이 없고 `gh auth status` 가 통과한다 | 현재 계정을 보여 주고 한 번 묻는다 — 그 계정에 비공개로 만들기(`gh repo create <폴더 이름> --private --source . --push`), 다른 레포 주소, 나중에. 만들었으면 push 결과(exit 0, 원격 URL)만 알린다 |
| origin 이 없고 gh 가 인증되지 않았다 | 사용자에게 고르게 한다 — 지금 `gh auth login` 하기(gh 가 없으면 설치부터), 이미 있는 레포 주소 알려 주기, 나중에 |

나중에를 고르면 다음 절로 간다. 턴 종료는 막히지 않고, 과업은 로컬에만 합쳐진다.
공개 여부만은 사람이 정한다. `--public` 은 명시 요청이 있을 때만 쓴다.

## 스택과 업무

사용자가 만들려는 업무 행동과 보존할 규칙을 먼저 확인한다.
언어와 프레임워크가 미정이면 후보의 실제 제약을 설명하고 사용자에게 선택을 요청한다.
하네스가 Python으로 돈다고 해서 제품 언어를 Python으로 간주하지 않는다.
기존 대화에서 결정한 사항은 다시 묻지 않는다.
빈 프로파일(`profiles/_template.py`)에서 시작해 선택한 언어와 검사 도구를 연결한다.

## 스택 맞춤

선택한 언어와 프레임워크의 팩이 게이트를 실제로 켜는지 확인한다.
커널에 팩이 있으면(Python·Go·TypeScript·Java) 그대로 쓰고, 없으면 그 언어로 하네스를 옮기는 일은 팩 파일 하나를 쓰는 것이다.
`profiles/lang/_template.py` 와 `profiles/framework/_template.py` 를 복사해 채운다.
새 언어팩은 `profiles/lang/<이름>.py` 에 두고 프로파일에 `LANG = "<이름>"` 을 적는다.
중괄호 언어(Kotlin·C#·Rust·Swift·PHP·Dart 등)는 `ANALYZER = "regex"` 에 함수 머리·import·최상위 이름 정규식 셋(`REGEX`)과 모듈 규칙(`MODULE_RULE`)·표준 라이브러리(`STDLIB`)를 적으면 설치 없이 구문 사실이 나온다.
팩에는 `FIXTURES`(위반·통과 예제)와, Python 에만 있는 검사 둘(`undefined_const`·`type_checking_future`)을 `NOT_APPLICABLE` 로 둔 사유도 적는다 — 빠지면 `pack_check` 가 미검증으로 남긴다.
이름 표기(`NAMING`)와 한 모듈만 맡을 기능(`OWNED`)도 같은 팩에 적는다. 실물 본보기는 `kernel/langs/java.py` 다.
정규식으로 안 되는 언어만 tree-sitter(`QUERIES`)나 외부 분석기 스크립트(`ANALYZER = "command"`)를 쓴다.
그 스크립트의 출력 계약은 `kernel/analyzers/command.py` 헤더를 따른다.
필요한 도구는 `python -X utf8 harness_install.py --doctor` 가 팩의 `REQUIRES` 로 보고한다.
설치는 사용자가 동의한 것만 하고, 하네스 본체 개발에는 아무것도 설치하지 않는다.
`python -X utf8 -m kernel.pack_check <이름>` 에 `[UNVERIFIED]` 가 없어야 끝난다.
설치에 동의한 도구는 `.github/workflows/harness.yml` 의 verify step 앞에도 적는다.
제품 테스트 명령이 정해졌으면 프로파일 `TESTS` 에 JUnit 보고서 자리 `{report}` 와 함께 선언하자고 제안한다. finish 와 CI 가 그 명령을 돌리고, 실행 0건은 실패로 친다(계약은 `dev/TESTING.md` 「하네스가 돌리는 제품 테스트」). 보고서를 만들 수 없는 도구면 선언하지 않고 그 사실을 사용자에게 말한다.
선택한 스택과 테스트 명령이 승인됐으면 `python -X utf8 -m kernel.preflight --configure`로 완료 설정을 채운다.
pytest 설정 파일이 있으면 그 실행 명령을 사용하며 다른 도구는 `--test-command` 뒤에 승인된 명령과 `{report}` 자리를 전달한다.
기존 테스트 명령과 필수 검사 목록은 보존한다.
설정 보완은 도구를 설치하지 않으며 명령을 확인할 수 없으면 파일을 고치지 않는다.
`harness_install.py --doctor`로 실행 파일과 모듈 및 누락한 완료 계약을 확인한다.
컴포넌트 그래프의 `technology` 가 선택한 언어와 다르면 `python -X utf8 -m kernel.graph_workflow bind` 로 이미 받은 스택 답을 결정으로 기록하고 다시 묻지 않는다.
스택 매니페스트(go.mod 나 package.json 같은 파일)는 프로파일 `ROOT_FILES` 에 사유와 함께 더한다.
무엇이 1급이고 무엇이 N/A 인지와 그 이유를 사용자에게 사람 말로 보고한다.
그다음 꼭 돌아야 하는 검사를 프로파일 `REQUIRED_CHECKS` 로 제안한다(예: 린터 slug, `test_pairing`, `tests`). 첫 컴포넌트가 생긴 뒤부터 그 검사가 꺼져 있으면 `--verify` 가 실패한다. 제안이고 강제하지 않는다. 목록을 줄이는 것은 완화라 편집 표면 래칫이 센다.

## 첫 분류와 승인

빈 프로젝트는 한 덩어리로 시작한다. 스택을 확인하는 질문에 "처음엔 코드를 한 덩어리로 두고 영역이 둘 이상 생기면 나누자고 제안합니다"를 함께 보이고, 그 답을 결정으로 기록한다.

```text
python -X utf8 -m kernel.graph_workflow starter --source src --response "실제 사용자 답변" --conversation "대화 참조"
```

코드가 이미 있거나 영역이 둘 이상이면 아래처럼 나눈다.
AI가 컴포넌트의 이름과 책임 및 제외 범위를 제안한다.
위치와 공개 계약 및 허용 의존 관계를 같은 제안에 포함한다.
사용자가 빈 양식을 채우도록 넘기지 않는다.
후보 그래프를 준비한 뒤 제안 명령으로 변경을 등록한다.

```text
python -X utf8 -m kernel.graph_workflow propose candidate.json --reason "업무 책임과 경계" --task "작업 이름"
```

AI가 등록한 제안을 사용자에게 보여주고 승인이나 수정 또는 거절을 묻는다.
실제 답변을 받은 뒤 제안 ID와 함께 기록한다.

```text
python -X utf8 -m kernel.graph_workflow decide <제안ID> --choice approve --response "실제 사용자 답변" --conversation "대화 참조"
python -X utf8 -m kernel.graph_workflow apply <제안ID>
```

거절은 reject로 기록하고 나중 결정은 defer로 기록한다.
응답이 없으면 승인으로 처리하지 않는다.
로컬 기록은 대화 답변과 변경안의 일관성을 검증하며 사용자 신원을 인증하지 않는다.
호스트 전용 알림 API에 기대지 않고 AI가 사용자에게 직접 묻는다.

## 구현과 검사

승인된 그래프의 책임과 경로에 맞춰 첫 코드를 배치한다.
선택한 언어의 소스 수집과 분석기 및 테스트 명령을 확인한다.
지원하지 않는 분석은 결과를 미검증으로 남기고 통과로 치지 않는다.
기능 지도를 생성하고 검증을 실행한다.

```text
python -X utf8 -m kernel.feature_map
python -X utf8 -m kernel.runner --verify
```

기존 승인 범위의 일반 편집은 질문 없이 진행한다.
새 분류나 경계가 필요해지면 해당 변경만 다시 제안한다.
아직 결정되지 않은 제안은 pending 명령으로 찾아 이어서 처리하고, 같은 제안을 다시 만들지 않는다.
