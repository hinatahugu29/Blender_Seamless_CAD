import json
import datetime

log_file = r"G:\blender_addon\Blender_CAD\agent-work-log.json"

with open(log_file, "r", encoding="utf-8") as f:
    logs = json.load(f)

new_log = {
  "timestamp": datetime.datetime.now().astimezone().isoformat(),
  "user_request_summary": "On Face機能実行時の core_bridge のインポートエラー修正依頼",
  "ai_interpretation": "スケッチモードで On Face を実行した際、`from ..core import core_bridge` という不正な相対パス指定により ImportError が発生していた。正しくは `from .. import core_bridge` であるためこれを修正し再デプロイする。",
  "status": "completed",
  "duration_minutes": 5,
  "files_changed": [
    "Blender_CAD_V_7_0_1/CAD_7_0_0/sketch/ops_reference_plane.py"
  ],
  "executed_actions": [
    "ops_reference_plane.py 内の不正なインポートパス `from ..core import core_bridge` を `from .. import core_bridge` に修正",
    "修正後、cad_server.exe を停止し deploy_v7.py でアドオンを再デプロイ"
  ],
  "uploaded_images": [],
  "notes": "軽微なパス指定ミスの修正。これで On Face 機能が実行可能になるはず。",
  "artifacts": []
}

logs.append(new_log)

with open(log_file, "w", encoding="utf-8") as f:
    json.dump(logs, f, ensure_ascii=False, indent=2)

print("Appended log.")
