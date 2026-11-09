# Wiem — Vision agent progress

## 2026-11-08 — Sprint 1
Done: Roboflow car damage dataset (sindhu/car_dent_scratch_detection-sekha v1, CC BY 4.0, 18 classes) with class → Damage(part, damage_type) mapping; leak-free split by source photo (1674 / 366 / 366 images, seed 42); dataset + baseline weights versioned with DVC and pushed to DagsHub; EDA notebook (0 leakage, 26% of boxes with part=unknown, 2 rare door classes, backlight = tail light); YOLOv8n baseline (CPU, 15 epochs, imgsz 640) logged to MLflow on DagsHub with required tags; agents/vision/agent.py run(claim) -> VisionResult (provisional severity rule, robust to missing/unreadable photos) + 9 tests in tests/vision/ (incl. one on the real weights).
Metrics: YOLOv8n baseline — test mAP50 = 0.183 (mAP50-95 0.089, P 0.290, R 0.248). MLflow run id 1978f3ebb19543b19d628bc34c0f9ef0 (experiment claimspilot-vision, DagsHub), data_version dvc:545b9cafe8c0be15216b8cbf7674f32e.dir.
Blocked by: claimspilot/schemas.py not on main yet (vision tests are skipped in CI until it exists); vision deps (pyyaml, ultralytics, torch CPU) missing in CI.
Next (sprint 2): merge severity variants into (part, damage_type) classes + separate severity rule to improve mAP50; retrain and register the model in the MLflow Model Registry; serve VisionResult through the API.

## 2026-11-08 — Sprint 2
Done: parts mapped to the shared vocabulary (unknown → other, tail_light → taillight); train.py loads .env (shared DagsHub MLflow); requirements-vision.txt; severity rule based on number, type and size of damages (+ Minor/Medium/Major hint as a floor), fully configurable in config.yaml; edge cases handled and tested (missing photo, unreadable photo, unmapped class, no damage).
Metrics: 12 vision tests passing (fake model in CI + 1 integration test on the real weights). Baseline unchanged: test mAP50 = 0.183, MLflow run 1978f3ebb19543b19d628bc34c0f9ef0.
Blocked by: PR #9 review (vocabulary + requirements); claimspilot/schemas.py on main (vision tests skipped in CI until then).
Next: register the model in the MLflow Model Registry; second training to compare (more epochs or YOLOv8s); run the agent on 3 sample claim photos.

## 2026-11-09 — Sprint 2
Done: second training to compare (stretch 8): YOLOv8n 30 epochs, logged directly to the shared DagsHub MLflow; train.py gets --name / --model options so comparison runs never overwrite the baseline; yolov8n_e30.pt versioned with DVC and used by the agent (config.yaml).
Metrics: yolov8n-e30 — test mAP50 = 0.199 (vs 0.183 baseline), mAP50-95 0.092, P 0.313, R 0.251. MLflow run id 7c062edcdbf94027b6484f220433c831. Longer training helps only slightly → the 18 severity-split classes are the main limit.
Blocked by: review of PR #9 and #10 (this PR is built on top of them); claimspilot/schemas.py on main.
Next: register yolov8n-e30 in the MLflow Model Registry (stretch 7); run the agent on 3 sample claim photos and share example VisionResult outputs with Hend and Mohamed.

## 2026-11-09 (2) — Sprint 2
Done: yolov8n-e30 registered in the MLflow Model Registry as `claimspilot-vision-yolo` v1 (stretch 7); demo script runs the agent on 3 test photos and saves real VisionResult JSON examples in agents/vision/examples/ for the NLP / policy / decision agents; missing weights now fail loudly instead of returning "no damage" (+ test).
Metrics: demo on 3 photos → 2 correct detections (headlight/crack 0.28, rear_bumper/dent 0.40), 1 missed damage (taillight, empty result) — consistent with recall 0.25. 13 vision tests passing.
Blocked by: review of PRs #9 → #10 → #11 (this PR is built on top of them).
Next: share the example VisionResults with Hend and Mohamed; if time allows, one more training with merged classes (part + damage type) to improve recall.

## 2026-11-09 (3) — Sprint 2
Done: classes merged from 18 to 8 (one per part + damage type) with merge_classes.py, since Minor/Medium/Major variants of the same damage were the main source of confusion and severity is computed by the rule anyway; merged dataset versioned with DVC; train.py --merged option; YOLOv8n retrained on merged classes (30 epochs, CPU) and used by the agent (config: weights + class_mapping); registered as `claimspilot-vision-yolo` v2; tests made independent of the configured model.
Metrics: yolov8n-merged-e30 — test mAP50 = 0.337 (vs 0.199 with 18 classes, +69%), mAP50-95 0.171, P 0.550, R 0.301. MLflow run id 5934a282b9ee484d8860ffd14349d674, data_version dvc:1c1798c74763dece81ee8a5cc6a2d8ee.dir. Note: 8-class mAP is an easier task than 18-class mAP, but it is exactly what the agent needs (part + damage type).
Blocked by: claimspilot/schemas.py on main; GPU access for YOLOv8s.
Next: YOLOv8s on merged classes on a GPU (Colab), as advised by our supervisor; propose the human-in-the-loop design at the Sunday checkpoint.