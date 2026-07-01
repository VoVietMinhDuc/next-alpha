# Ghi chú kiến thức RAG — OptiBot

Tổng hợp những gì đã trao đổi khi tìm hiểu về chunking, token và RAG cho project
OptiBot (Gemini File Search). Viết dưới góc nhìn của project này để tham khảo lại.

---

## 1. Chunk và token — hiểu cho đúng

### Chunk nhỏ có tốn ít token hơn không?
**Không** — ngược lại là đằng khác. Cần tách rõ 2 thời điểm token phát sinh:

| Thời điểm | Chunk nhỏ vs to | Ghi chú |
|---|---|---|
| **Lúc lưu** (embed vào store) | Gần như bằng nhau | Chunk nhỏ còn tốn **hơn một chút** do overlap lặp lại |
| **Lúc hỏi** (nhét chunk vào prompt) | Nhỏ = tốn ít **input** hơn | Đây mới là chỗ đáng quan tâm |

### Vì sao lúc lưu tổng token gần như không đổi
Ví dụ 1 file 1000 token, `MAX_OVERLAP_TOKENS = 100`:
- Băm to (2 chunk): phần lặp = 100 → embed ~1100 token
- Băm nhỏ (5 chunk): phần lặp = 4×100 = 400 → embed ~1400 token

→ Băm càng nhiều chunk → overlap lặp càng nhiều → tốn **hơn một chút**, nhưng
không đáng kể ở quy mô project này.

### Điểm dễ nhầm: nhỏ tiết kiệm INPUT, không phải OUTPUT
- **Output token** = độ dài câu trả lời model viết ra → phụ thuộc câu trả lời dài
  hay ngắn, KHÔNG liên quan chunk to/nhỏ.
- **Input token** = phần tài liệu nhét vào prompt → chunk nhỏ giúp giảm cái này.

---

## 2. Cấu hình chunking trong code

Trong [../src/uploader.py](../src/uploader.py):

```python
MAX_TOKENS_PER_CHUNK = 500   # trần (max), KHÔNG phải kích thước cố định
MAX_OVERLAP_TOKENS = 100
```

- **500 là mức trần**, vì Gemini File Search cap tối đa **512 token/chunk**. Mỗi
  chunk sẽ ≤ 500, cắt theo ranh giới từ/câu (`white_space_config`) nên thường hơi
  ít hơn 500 để không cắt giữa từ.
- **Chunk cuối** chỉ chứa phần thừa còn lại của file → thường **không đầy 500**.
  Ví dụ file 1000 token → chunk cuối (800–1000) chỉ ~200 token.
- **Stride** (bước nhảy) = 500 − 100 = 400 token mỗi chunk. Đây là căn cứ của hàm
  `estimate_chunks`.

Lưu ý: `estimate_chunks` đếm **số chunk (số mảnh)**, khác với **số token**.

### Các hướng cắt chunk khác (không dùng ở đây)
Project này cắt theo **số token cố định** (`white_space_config`) cho đơn giản. Còn
có những cách khác:

- **Semantic chunking** — cắt theo **ý nghĩa** (hết đoạn, hết ý) thay vì theo số
  token cố định. Chất lượng tốt hơn (không cắt ngang mạch ý) nhưng **phức tạp hơn**
  (phải phân tích ngữ nghĩa để tìm điểm cắt).
- **Cắt theo cấu trúc Markdown** — mỗi heading một chunk. Hợp với tài liệu có
  heading rõ ràng. Ở đây tác giả để **Gemini tự lo** việc chunk nên không tự cắt
  theo heading.

→ Với support article ngắn, cắt theo token cố định là đủ tốt và ít công. Các hướng
trên đáng cân nhắc khi tài liệu dài/có cấu trúc phức tạp.

---

## 3. Đếm token của 1 file .md

### Cách 1 — Ước lượng nhanh (offline)
Quy tắc `CHARS_PER_TOKEN = 4`: **số token ≈ số ký tự ÷ 4**.
- Tiếng Anh: ~4 ký tự/token
- Tiếng Việt: tốn hơn, ~2–3 ký tự/token

### Cách 2 — Chính xác (gọi Gemini)
```python
from google import genai
from src import config

client = genai.Client(api_key=config.API_KEY)
text = open("data/articles/ten-bai.md", encoding="utf-8").read()
result = client.models.count_tokens(model="gemini-2.5-flash", contents=text)
print(result.total_tokens, "tokens")
```

### Có cần quan tâm token mỗi bài không?
Với quy mô project này (vài chục–vài trăm article, embed 1 lần): **hầu như không
cần**. Embedding rất rẻ. Chỉ đáng quan tâm khi: quy mô lớn (hàng triệu doc,
re-embed thường xuyên), hoặc lo 1 bài vượt context window.

---

## 4. Token lúc trả lời (query)

Đây mới là chỗ tốn tiền thật. Khi chạy `python -m src.ask "..."`, luồng là:

```
Câu hỏi → Gemini tìm trong store → lấy vài chunk liên quan
        → GHÉP chunk vào prompt → gửi LLM → sinh câu trả lời
```

### Input token (đẩy vào model)
| Thành phần | Nguồn | Cỡ token |
|---|---|---|
| System prompt | `SYSTEM_INSTRUCTION` | ~60 (cố định mỗi lần) |
| Câu hỏi | `question` | ~10–30 |
| **Chunk lấy từ store** | `file_search` tự chèn | **Lớn nhất** — vài trăm→vài nghìn |

### Output token (model sinh ra)
Là câu trả lời. System prompt giới hạn "max 5 bullet, cite ≤3 URL" nên output nhỏ
(~100–300 token). **Output đắt hơn input mỗi token** (Gemini: output ~4× input).

### Đo token thật mỗi câu hỏi
Thêm vào chỗ in kết quả trong [../src/ask.py](../src/ask.py):
```python
um = resp.usage_metadata
print(f"input: {um.prompt_token_count} | output: {um.candidates_token_count} "
      f"| tổng: {um.total_token_count}")
```

---

## 5. Top-k

**Top-k** = số chunk lấy ra để đưa vào prompt trả lời ("lấy k mảnh đầu bảng theo
độ liên quan").

| | Top-k cao (vd 20) | Top-k thấp (vd 3) |
|---|---|---|
| Token input | Nhiều → tốn tiền | Ít → rẻ |
| Ngữ cảnh | Đầy đủ, ít sót | Có thể thiếu |
| Nhiễu | Nhiều rác, dễ lạc | Sạch, tập trung |

→ Không phải càng cao càng tốt. Thường **3–8** là hợp lý.

### Gemini đang tự chọn top-k dựa trên cái gì?
Code hiện tại **không set top_k** → Gemini tự quyết. Cơ chế (chắc chắn): chọn theo
**độ tương đồng ngữ nghĩa** — embed câu hỏi → so vector với các chunk → xếp hạng →
lấy điểm cao nhất. Con số/ngưỡng mặc định cụ thể thì Google **không công bố** (hộp
đen managed).

### Có cần set top_k không?
**Không cần** với project này: quy mô nhỏ, là demo/deliverable, system prompt đã
kìm output. Chỉ chỉnh khi thấy triệu chứng thật (trả lời thiếu → tăng; lan man/tốn
token bất thường → giảm). Nguyên tắc: **đo trước, chỉnh sau**.

---

## 6. Chunk nhỏ có phải luôn thắng? — Khi nào dùng chunk TO

Chọn chunk là đánh đổi **độ chính xác ↔ ngữ cảnh**, không chỉ là token:

| | Chunk nhỏ | Chunk to |
|---|---|---|
| Retrieval | Trúng đích, chính xác | Dễ lẫn, kém chính xác |
| Ngữ cảnh | Dễ bị cắt cụt ý | Đầy đủ, mạch lạc |
| Token input | Ít | Nhiều |

### Khi nào cố tình dùng chunk to
1. Tài liệu cần mạch văn liền (hợp đồng, truyện, code file)
2. Câu hỏi cần cái nhìn tổng thể (tóm tắt, giải thích cả quy trình)
3. Model context window lớn (Gemini 2.5 nhét cả triệu token → bớt cần chunk nhỏ)

### "Ăn cả hai": Small-to-Big (parent-document retrieval)
- **Tìm kiếm** trên chunk **nhỏ** (chính xác)
- Nhưng **đưa vào prompt** cả đoạn **cha to hơn** (đủ ngữ cảnh)
→ Vừa trúng đích vừa không cụt ý.

### Với OptiBot
Support article ngắn, từng bước rõ ràng → chunk vừa (500/100) là đúng bài. Không
nên nhỏ hơn (kẻo cắt ngang các bước), cũng không cần to hơn. Đang ở điểm cân bằng.

---

## 7. Kiến thức RAG nền tảng nên biết

1. **Embedding** — biến text → vector đại diện *ý nghĩa*. Nghĩa giống nhau thì
   vector gần nhau. "Tìm chunk liên quan" = so khoảng cách vector. Gemini File
   Search làm ngầm hết.

2. **Rác vào → rác ra** (quan trọng nhất) — RAG chỉ tốt bằng chất lượng tài liệu.
   Bước scraper làm sạch HTML + prepend "Article URL:" quan trọng hơn cả tinh
   chỉnh top-k. Đa số lỗi RAG nằm ở khâu chuẩn bị dữ liệu.

3. **Grounding & hallucination** — "Only answer using the uploaded docs" là
   grounding, nhưng không đảm bảo 100%. Cách chống: bắt trích dẫn nguồn (đã làm
   với "Article URL:") để kiểm chứng.

4. **Dữ liệu cũ / re-index** — tài liệu đổi thì store phải cập nhật. Việc của
   [../src/delta.py](../src/delta.py): chỉ up file đổi, và **xóa bản cũ trước khi
   up bản mới** (nếu không → 2 phiên bản cùng tồn tại → trả lời mâu thuẫn). Cạm
   bẫy RAG kinh điển.

5. **Đánh giá (evaluation)** — soạn 10–20 câu hỏi + đáp án mong đợi, chạy thử, xem
   đúng mấy câu + cite đúng URL không. Có bộ test này thì mỗi lần chỉnh chunk/prompt
   đều **đo được** tốt lên hay tệ đi, thay vì đoán.

6. **Reranking** — dùng thêm 1 model xếp hạng lại chunk sau khi retrieve. Hữu ích
   khi store lớn. Với project này chưa cần (Gemini File Search lo rồi).

---

## 8. Ưu tiên cho project này

| Nên đầu tư | Đừng bận tâm giờ |
|---|---|
| Chất lượng chunk/scraper (#2) | Reranking (#6) |
| Delta xóa bản cũ (#4) | Tinh chỉnh top-k |
| Bộ câu hỏi test (#5) | Đếm token mỗi bài |

**Nếu chọn 1 việc làm tiếp:** dựng bộ eval nhỏ (#5) — biến mọi tranh luận "chunk
vầy ổn chưa / top-k bao nhiêu" thành đo được bằng số.

---

## 9. Đồng bộ store (Part 3) — các hướng & lựa chọn

Bài toán: giữ store trên Gemini khớp với tập article scrape được. Một sync đầy đủ
phải xử lý 3 loại thay đổi: **Added** (up mới), **Updated** (thay bản cũ),
**Removed** (xóa bài đã gỡ ở nguồn).

| Hướng | Chi phí/run | Chống duplicate | Xử lý Removed | Phức tạp | Rủi ro chính |
|---|---|---|---|---|---|
| **A** Rebuild (đập đi xây lại) | Cao (toàn bộ) | ✅ | ✅ | Thấp | Khoảng trống lúc rebuild |
| **B** Delta không xóa | Thấp | ❌ | ❌ | Thấp | Sai dần, rác tích tụ |
| **C** Delta có xóa (upsert) | Thấp | ✅ | ✅* | Trung bình | State lệch, không atomic |
| **D** Store là nguồn sự thật | Trung bình | ✅ | ✅ | Trung–cao | List tốn, cần hash trong metadata |
| **E** Blue-green (build mới rồi đổi cờ) | Cao | ✅ | ✅ | Cao | Tốn gấp đôi, điều phối |

### Đã chọn: Hướng C
Lý do: **đề bài chốt cứng** *"uploads only what changed"* + log added/updated/skipped
→ loại A/B. C là hướng đề bài đã vẽ sẵn (`state.json`, hash-based diff). D/E thừa
cho một daily job internal quy mô nhỏ.

Cách làm production trong code:
- **Upsert theo slug** — `upload_files` xóa document cũ cùng `display_name` trước
  khi index bản mới → update không đẻ duplicate, chạy lại job cũng không trùng
  (idempotent).
- **Ghi `state.json` SAU khi up thành công** — up lỗi thì không lưu state → lần sau
  tự retry; retry an toàn vì upsert idempotent.
- **`_wait` có timeout + check `operation.error`** — operation treo/lỗi thì fail
  lớn tiếng, không treo job hay báo nhầm thành công.

### (*) Hạn chế đã biết: chưa xử lý Removed
Code hiện làm added/updated/skipped, **chưa xóa** bài bị gỡ ở nguồn (document chết
còn nằm trong store tới lần rebuild). Nằm ngoài hợp đồng add/update/skip của đề
bài; muốn thêm thì diff slug hiện tại với slug trong state cũ rồi xóa phần chênh.
