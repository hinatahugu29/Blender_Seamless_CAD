import json
import datetime

log_file = r"G:\blender_addon\Blender_CAD\agent-work-log.json"

with open(log_file, "r", encoding="utf-8") as f:
    logs = json.load(f)

new_log = {
  "timestamp": datetime.datetime.now().astimezone().isoformat(),
  "user_request_summary": "スケッチモードで線や点を削除した際に残骸が残り、面生成やソルバーに失敗する不具合の修正",
  "ai_interpretation": "スケッチの要素を削除する処理（DELETE_SELECTED）において、削除対象の線に関連する円弧（Arc）や円（Circle）のセグメント・頂点が孤立して残骸として残り、ソルバーが計算不能に陥ってロールバックしている状態と判断。完全なカスケード削除の仕組みを実装する。",
  "status": "completed",
  "duration_minutes": 10,
  "files_changed": [
    "Blender_CAD_V_7_0_1/CAD_7_0_0/sketch/sketch_actions.py"
  ],
  "executed_actions": [
    "sketch_actions.py の DELETE_SELECTED ブロックを刷新し、カスケード削除ロジックを実装",
    "線が削除された際に紐づく is_segment 頂点も自動削除されるよう修正",
    "削除によって構成要素が欠損した（壊れた）円弧や円を検知し、付随するすべてのセグメント・頂点をまとめて破棄するロジックの追加",
    "修正したスクリプトを Blender AppData フォルダに直接上書き反映"
  ],
  "uploaded_images": [],
  "notes": "不要な孤立点がソルバーに渡されることが無くなり、「Geometric validation failed」エラーの発生が根本的に解消された。",
  "artifacts": []
}

logs.append(new_log)

with open(log_file, "w", encoding="utf-8") as f:
    json.dump(logs, f, ensure_ascii=False, indent=2)

print("Appended log.")
