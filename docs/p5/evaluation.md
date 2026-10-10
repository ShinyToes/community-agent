# P5 有限样例评测入口

`tools/evaluate_p5.py`读取独立标注的 JSON，比较明确名称、固定扩展和有界探索在**同一批已知样例**上的发现、筛选与成本。脚本只算数，不调用模型或爬虫。当前尚无真实人工标注集合，因此没有真实质量分数；P0 的虚构数据仅用于程序验证。

## 样例文件

```json
{
  "cases": [
    {
      "id": "case_001",
      "gold": {"post_1": "relevant", "post_2": "irrelevant", "post_3": "drift", "post_4": "uncertain"},
      "methods": {
        "explicit_name": {"candidate_ids": ["post_1"], "selected_ids": ["post_1"], "requests": 1, "model_calls": 0, "seconds": 1.2},
        "fixed_expansion": {"candidate_ids": ["post_1", "post_2"], "selected_ids": ["post_1"], "requests": 2, "model_calls": 1, "seconds": 2.5},
        "bounded_exploration": {"candidate_ids": ["post_1", "post_3", "post_4"], "selected_ids": ["post_1", "post_4"], "requests": 3, "model_calls": 2, "seconds": 4.0}
      }
    }
  ]
}
```

这里的 ID 和数值仅演示格式，不能作为项目效果。真实评测时先固定问题、时间范围、采集来源和预算，并保存原文快照；标注者不参考模型判定，逐条给出 `relevant`、`irrelevant`、`uncertain` 或 `drift`。三种方法在相同采集权限和上限下运行，记录实际候选 ID、正式选择 ID、请求数、模型调用和耗时。多个方法共享相同标注集合，新增候选先补标，未知项不能偷偷算作无关。

```powershell
.\MediaCrawler\.venv\Scripts\python.exe tools/evaluate_p5.py path\to\study.json --output path\to\report.json
```

报告中的 `known_sample_recall` 只以标注集合内的相关项为分母；`judged_precision` 不把未知和待核实项当作正确或错误，另列未知数量。`selected_drift` 计入被选中的跨目标项；重复候选与请求、调用、耗时分别记录。没有相关金标或没有可判断的已选项时相应比率为 `null`。这些数字均不代表贴吧或其他平台的全量召回率，也不能由模型自评替代人工标注。
