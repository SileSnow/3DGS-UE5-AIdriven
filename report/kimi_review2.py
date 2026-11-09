# -*- coding: utf-8 -*-
import json, re, urllib.request, urllib.error
cred = open(r"C:\Users\Lenovo\.dsh\.credentials.yaml", encoding="utf-8").read()
key = re.search(r"KIMI_API_KEY:\s*(\S+)", cred).group(1).strip().strip('"').strip("'")
brief = open(r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\report\kimi_brief.md", encoding="utf-8").read()
payload = {"model": "kimi-k3.1-pro", "thinking": {"type": "disabled"},
           "messages": [{"role": "system", "content": "你是顶级演示视频导演。先给结论，再给可执行方案；中文 Markdown，不要空话。"},
                        {"role": "user", "content": brief}],
           "max_tokens": 8000, "temperature": 0.7}
req = urllib.request.Request("https://api.moonshot.cn/v1/chat/completions", data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
try:
    r = json.load(urllib.request.urlopen(req, timeout=300))
    msg = r["choices"][0]["message"]; content = msg.get("content") or ""
    out = r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\report\kimi_video_review.md"
    open(out, "w", encoding="utf-8").write(content)
    print("finish:", r["choices"][0].get("finish_reason"), "chars:", len(content), "usage:", json.dumps(r.get("usage", {}), ensure_ascii=False)[:200])
    print("=== REVIEW ===")
    print(content[:5000])
except Exception as e:
    print("ERR", type(e).__name__, str(e)[:400])
