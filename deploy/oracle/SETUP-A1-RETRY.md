# 서버에서 A1 재시도 돌리기 (컴퓨터를 꺼도 계속)

항상 켜져 있는 Oracle Micro 서버(`topic-thread`)가 **Instance Principal**(서버 자신의 신원)로 OCI에 로그인해서,
무료 A1 서버(`topic-thread-a1`, 2 OCPU / 12GB)가 만들어질 때까지 60초마다 생성을 시도한다.
API 키 같은 비밀 값을 서버에 저장하지 않는다.

## 1. IAM 권한 만들기 (콘솔에서 직접)

### 1-1. 동적 그룹
메뉴 → Identity & Security → **Domains** → `Default` → **Dynamic groups** → Create dynamic group
- 이름: `topic-thread-dg`
- 규칙(Matching rule): 

```
instance.id = 'ocid1.instance.oc1.ap-osaka-1.anvwsljrnxefgeac2je3i4mjspdyfrfpu4kntmrxzleck7laauyqbj6lhiia'
```

### 1-2. 정책
메뉴 → Identity & Security → **Policies** → Create Policy (compartment: root)
- 이름: `topic-thread-a1-policy`
- Policy statements (Identity Domain을 쓰는 계정이면 그룹 이름을 `'Default'/'topic-thread-dg'` 형태로):

```
Allow dynamic-group 'Default'/'topic-thread-dg' to manage instance-family in tenancy
Allow dynamic-group 'Default'/'topic-thread-dg' to use virtual-network-family in tenancy
Allow dynamic-group 'Default'/'topic-thread-dg' to read images in tenancy
```

(도메인 표기가 안 맞으면 `Allow dynamic-group topic-thread-dg to ...`로 시도)

## 2. 서버에서 실행 (권한을 만든 뒤)
```bash
sudo cp ~/a1-retry.service /etc/systemd/system/a1-retry.service
sudo systemctl daemon-reload
sudo systemctl enable --now a1-retry
tail -f ~/a1-retry.log
```
- 성공하면 로그에 `CREATED: ocid1.instance...`가 찍히고 서비스가 종료된다.
- 중지: `sudo systemctl disable --now a1-retry`
- 권한 오류(`NotAuthorized`, `NotAuthenticated`)가 로그에 나오면 정책 문구/그룹 이름을 확인한다.

## 3. 성공 후
- 새 서버로 데이터 이전, DNS(DuckDNS) 변경, 임시 제한 해제. 완료되면 위 IAM 정책/동적 그룹은 삭제한다.
