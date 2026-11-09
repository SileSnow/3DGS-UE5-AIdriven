# -*- coding: utf-8 -*-
import json, re, urllib.request, urllib.error
cred = open(r"C:\Users\Lenovo\.dsh\.credentials.yaml", encoding="utf-8").read()
key = re.search(r"KIMI_API_KEY:\s*(\S+)", cred).group(1).strip().strip('"').strip("'")
brief = open(r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\report\kimi_brief.md", encoding="utf-8").read()
payload = {"model": "kimi-k3.1-pro", "thinking": {"type": "disabled"},
           "messages": [{"role": "system", "content": "你是顶级演示视频导演。先给结论，再给可执行方案；中文 Markdown，不要空话。"},
                        {"role": "user", "content": brief}],
           "max_tokens": 8000}
req = urllib.request.Request("https://api.moonshot.cn/v1/chat/completions", data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
r = json.load(urllib.request.urlopen(req, timeout=300))
content = r["choices"][0]["message"].get("content") or ""
out = r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\report\kimi_video_review.md"
open(out, "w", encoding="utf-8").write(content)
print("finish:", r["choices"][0].get("finish_reason"), "chars:", len(content))
print("saved:", out)
print(content[4000:8500])
