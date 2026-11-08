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