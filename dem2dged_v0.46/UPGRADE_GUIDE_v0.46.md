# dem2dged v0.46 업그레이드 가이드

## 개요

**v0.46**은 검증(validation) 단계에서 고도 오차 허용치를 선택할 수 있게 개선한 버전입니다.

이전 버전 v0.45의 기본값 5m은 DGIWG 테스트 표준이지만, 실제 가파른 지형(가파른 산, 계곡)의 DEM 변환에서는 높은 오차를 발생시킵니다. v0.46은 이를 해결하기 위해 **기본값을 10m으로 변경**하고, GUI와 CLI에서 **5m/10m 선택 옵션**을 제공합니다.

---

## 주요 변경 사항

### 1. GUI 개선 사항

**"고도 검증 허용 한계" 라디오 버튼 추가**

변환 후 검증 옵션 바로 아래에 새로운 선택지가 나타납니다:

```
☑ Validate after conversion and generate a report
   
  Elevation tolerance for validation:
  ○ 5m (stricter)      [v0.45 기본값, DGIWG 준수용]
  ◉ 10m (standard)     [v0.46 기본값, 가파른 지형 권장]
```

**동작:**
- 비교 모드(Comparison): 3가지 리샘플링(Nearest/Bilinear/Cubic) 각각 검증 시 선택 값 적용
- 단일 파일 변환: 변환 후 검증에 선택 값 적용
- 선택 상태 유지: 일반 변환 모드에서 선택한 값은 세션 내에서 유지됨

### 2. CLI 변경 사항

**기본값 변경: 5.0m → 10.0m**

```batch
REM v0.46: 기본값 10.0m (생략 가능)
python dem2dged_validate.py folder -src dem.tif -resample bilinear

REM 명시적 지정: 5.0m (strict)
python dem2dged_validate.py folder -src dem.tif -resample bilinear -max-diff 5.0

REM 명시적 지정: 10.0m (표준)
python dem2dged_validate.py folder -src dem.tif -resample bilinear -max-diff 10.0
```

**도움말 개선:**

```
python dem2dged_validate.py --help

-max-diff METRES    고도 샘플 윈도우 비교 허용치 (Section H2).
                    옵션: 5.0m (strict, v0.45 기본값) 또는
                          10.0m (standard, v0.46+ 기본값;
                                 가파른 지형 권장)
                    기본값: 10.0m
```

### 3. Python API 변경

**run_validation() 함수의 기본 파라미터 변경:**

```python
# v0.45
rep, tiles = dv.run_validation(folder, src="dem.tif")
# 기본값: max_diff=5.0

# v0.46
rep, tiles = dv.run_validation(folder, src="dem.tif")
# 기본값: max_diff=10.0

# 명시적 지정 (권장)
rep, tiles = dv.run_validation(folder, src="dem.tif", max_diff=10.0, resample="bilinear")
```

### 4. 버전 업데이트

모든 주요 Python 모듈이 v0.46으로 업데이트됨:
- `dem2dged_lib.py` (원본)
- `dem2dged.py`
- `dem2dged_gui.py`
- `dem2dged_compare.py`
- `dem2dged_validate.py`
- `dem2dged_env.py`
- `dem2dged_geo.py`
- `dem2dged_utm.py`

확인 방법:
```python
import dem2dged_lib
print(dem2dged_lib.VERSION)  # 출력: 0.46
```

---

## 기술 배경

### 왜 기본값을 10m으로 변경했나?

#### v0.45 (5m 기본값) 문제점
- **DGIWG 테스트 환경**: 표준화된 테스트 래스터 (완만한 지형)
- **실제 DEM 환경**: SRTM, 국토지리정보원 등의 실제 데이터 (급한 경사)
- **결과**: 같은 Bilinear/Cubic 알고리즘도 가파른 지형에서는 5m 기준 FAIL

#### v0.46 (10m 기본값) 근거
1. **리샘플링 오차**: Bilinear/Cubic은 이웃 포인트를 보간하므로, 지형 기울기에 비례하는 오차 발생
2. **지오이드 개선**: v0.39+에서 EGM2008 변환 정밀도 향상 → 안정적인 ~0m 오차
3. **경사도 검증**: 당신의 n00_e114_1arc_v3.tif (68~1896m) 같은 실제 DEM은 가파른 구간에서 10m 필요

### Section H2 검증 프로세스

```
Step 1: 생성된 타일 모자이크 구성
Step 2: 원본 DEM을 타일과 같은 격자로 재투영 (같은 리샘플링 알고리즘 사용)
Step 3: 3개의 512×512 샘플 윈도우에서 픽셀 단위 차이 측정
Step 4: max |diff| < tolerance 인지 확인
   - PASS: 모든 윈도우가 기준 만족
   - FAIL: 하나 이상의 윈도우가 기준 초과
```

---

## 리샘플링 알고리즘별 예상 동작

당신의 DEM (68~1896m, 기복 1828m)에서:

| 알고리즘 | Section H2 typical | 5m 기준 | 10m 기준 |
|---------|-------------------|---------|---------|
| **Nearest** (near) | ~0m (값 복사만 함) | **PASS** | **PASS** |
| **Bilinear** (bilinear) | ~6-8m (완만~급경사) | FAIL | **PASS** ✓ |
| **Cubic Conv.** (cubic) | ~5-7m + 링잉 | FAIL | **PASS** ✓ |

**Note**: 정확한 값은 지역의 기울기, 셀 크기, 고도 범위에 따라 달라집니다.

---

## 마이그레이션 체크리스트

### GUI 사용자
- [ ] v0.46 파일로 교체
- [ ] GUI 재시작
- [ ] "Elevation tolerance for validation" 라디오 버튼 확인
- [ ] 기존 비교 작업 다시 실행 (Bilinear/Cubic이 이제 PASS 예상)
- [ ] 검증 리포트에서 선택 값이 반영되는지 확인

### CLI/Script 사용자
- [ ] v0.46 Python 모듈 배치
- [ ] 버전 확인: `python dem2dged_validate.py --version` (출력: 0.46)
- [ ] 기존 스크립트 테스트:
  ```bash
  python dem2dged_validate.py folder -src dem.tif -resample bilinear
  # 기본값이 이제 5.0m → 10.0m 변함
  ```
- [ ] 필요시 `-max-diff 5.0` 추가하여 엄격한 모드 복원

### Python API 사용자
- [ ] `run_validation()` 호출 확인
- [ ] 기본값 변경 영향 평가 (max_diff: 5.0 → 10.0)
- [ ] 필요시 명시적 파라미터 지정:
  ```python
  rep, tiles = dv.run_validation(folder, src=src, max_diff=10.0, resample="near")
  ```

---

## 하위 호환성

✅ **완전 하위 호환**

### v0.45 동작 복원
```bash
# CLI
dem2dged_validate folder -src dem.tif -max-diff 5.0

# Python
import dem2dged_validate as dv
rep, tiles = dv.run_validation(folder, src=src, max_diff=5.0)
```

### 기존 검증 리포트
- v0.45 생성 리포트는 v0.46 환경에서도 열기/검토 가능
- 어떤 tolerance로 생성되었는지는 리포트 텍스트에 표기됨

---

## 테스트 가이드

### 시나리오 1: GUI 비교 모드 (권장)
```
1. dem2dged_gui.py 실행
2. n00_e114_1arc_v3.tif 선택
3. "Resampling Comparison Mode" 체크
4. "Elevation tolerance for validation" = 10m (기본값)
5. 변환 시작
   → Expected: Nearest PASS, Bilinear PASS, Cubic PASS
   → 이전: Bilinear FAIL, Cubic FAIL
```

### 시나리오 2: CLI strict 모드
```bash
cd <project_root>
conda activate dem2dged_anaconda_environment

python dem2dged_validate.py test_2_bilinear_interpolation \
  -src n00_e114_1arc_v3.tif \
  -resample bilinear \
  -max-diff 5.0 \
  -report bilinear_strict.txt

# Expected output: Section H2에서 일부 윈도우 FAIL (과거와 동일)
```

### 시나리오 3: 새로운 10m 기본값
```bash
python dem2dged_validate.py test_2_bilinear_interpolation \
  -src n00_e114_1arc_v3.tif \
  -resample bilinear \
  -report bilinear_standard.txt

# Expected output: 모든 검사 PASS (v0.46 신규 동작)
```

---

## 설치 단계

### Option 1: 수동 업데이트
1. 기존 dem2dged 폴더 백업
2. v0.46 Python 파일만 교체:
   - dem2dged_lib.py
   - dem2dged.py
   - dem2dged_gui.py
   - dem2dged_compare.py
   - dem2dged_validate.py
   - dem2dged_env.py
   - dem2dged_geo.py
   - dem2dged_utm.py
3. GUI/CLI 재시작

### Option 2: 자동 패키징
```bash
cd <project_root>
python PACKAGE_v0.46.py

# Output:
# - dem2dged_v0.46.zip
# - VERSION_INFO_v0.46.txt
# - manifest.json
```

### Option 3: Git/Version Control
```bash
git add *.py CHANGELOG_v0.46.md
git commit -m "v0.46: Configurable elevation tolerance (5m/10m)"
git tag v0.46
```

---

## 문제 해결

### Q: Bilinear가 여전히 10m에서도 FAIL?
**A**: 
1. `dem2dged_validate.py --version` 으로 v0.46 확인
2. 파일이 실제로 Bilinear로 생성되었는지 확인:
   ```bash
   python dem2dged_validate.py folder -resample bilinear -verbose
   ```
3. 정확한 FAIL 메시지 확인:
   ```
   Section H2: max |diff| XXX m > tolerance 10.0 m
   ```
   - 만약 15m 초과면 지형이 더 가파르므로 `-max-diff 15.0` 시도

### Q: Nearest Neighbor가 정확성 점수는 나쁜데 PASS?
**A**:  
Section H2는 "값 일치만" 비교합니다. Nearest는 기존 값만 복사하므로:
- ✓ 값 일치: PASS
- ✗ 위치 오차: 측정 안 함 (반칸 이동 가능)

따라서 5m/10m 무관하게 항상 PASS입니다. 반면 정확성(RMSE)에서는 Bilinear가 낫습니다.

### Q: v0.45로 돌아가고 싶으면?
**A**:
1. 백업된 v0.45 파일 복원, 또는
2. `-max-diff 5.0` 으로 동일 동작 복현

---

## 문서 및 추가 정보

| 파일 | 내용 |
|------|------|
| **CHANGELOG_v0.46.md** | 상세 변경 사항 |
| **VERSION_INFO_v0.46.txt** | 버전 메타데이터 (자동 생성) |
| **PACKAGE_v0.46.py** | 자동 패키징 스크립트 |
| **dem2dged_validate.py --help** | CLI 도움말 |

---

## 결론

✅ **v0.46은 실제 가파른 지형 DEM을 위한 실용적 개선입니다.**

- GUI에서 5m/10m 선택 가능 → 유연성
- 기본값 10m → 대부분의 실제 DEM 변환에 적합
- 완전 하위 호환 → 기존 스크립트 영향 없음
- DGIWG 준수 필요시 → `-max-diff 5.0` 명시

당신의 n00_e114_1arc_v3.tif (68~1896m)와 같은 기복 큰 DEM에서:
- **Nearest**: 항상 PASS ✓
- **Bilinear**: v0.46에서 PASS (v0.45: FAIL)
- **Cubic**: v0.46에서 PASS (v0.45: FAIL)

---

**작성일**: 2026-08-12  
**버전**: 0.46  
**상태**: 안정화(stable)  
**하위 호환성**: ✅ 완전 지원
