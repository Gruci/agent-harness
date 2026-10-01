# 프로젝트 하네스 조립

> 담는 것: 언어 선택부터 첫 코드의 분류와 검사 연결까지의 절차. 담지 않는 것: 그래프 승인 계약(→ [../COMPONENTS.md](../COMPONENTS.md)). 읽는 시점: 새 프로젝트를 시작하거나 기술 스택을 바꿀 때.

## 스택과 업무

사용자가 만들려는 업무 행동과 보존할 규칙을 먼저 확인한다.
언어와 프레임워크가 미정이면 후보의 실제 제약을 설명하고 사용자에게 선택을 요청한다.
하네스가 Python으로 돈다고 해서 제품 언어를 Python으로 간주하지 않는다.
기존 대화에서 결정한 사항은 다시 묻지 않는다.
빈 프로파일(`profiles/_template.py`)에서 시작해 선택한 언어와 검사 도구를 연결한다.

## 스택 맞춤

선택한 언어와 프레임워크의 팩이 게이트를 실제로 켜는지 확인한다.
커널에 팩이 있으면 그대로 쓰고, 없으면 `profiles/lang/_template.py` 와 `profiles/framework/_template.py` 를 복사해 채운다.
tree-sitter 를 설치할 수 없으면 언어팩에 `ANALYZER = "command"` 를 두고 외부 분석기 스크립트를 만든다.
그 스크립트의 출력 계약은 `kernel/analyzers/command.py` 헤더를 따른다.
필요한 도구는 `python -X utf8 harness_install.py --doctor` 가 팩의 `REQUIRES` 로 보고한다.
설치는 사용자가 동의한 것만 하고, 하네스 본체 개발에는 아무것도 설치하지 않는다.
`python -X utf8 -m kernel.pack_check <이름>` 에 `[UNVERIFIED]` 가 없어야 끝난다.
무엇이 1급이고 무엇이 N/A 인지와 그 이유를 사용자에게 사람 말로 보고한다.

## 첫 분류와 승인

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
