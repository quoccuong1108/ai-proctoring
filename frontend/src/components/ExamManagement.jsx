import ModalShell from "./ModalShell";
/**
 * EduShield AI — ExamManagement (Quản lý Đề thi, dành cho Giảng viên)
 *
 * Bao phủ toàn bộ Phần A + Phần C của module Đề thi (xem exams_router.py):
 *   1. Upload file .xlsx/.docx theo mẫu -> xem trước kết quả đọc file (kèm lỗi nếu có)
 *   2. Danh sách đề thi đã tạo (mọi trạng thái), công bố (Publish) đề DRAFT, xóa đề
 *   3. Xem bảng điểm 1 đề thi (kèm số lần vi phạm ghép từ module Giám sát)
 *   4. Xuất bảng điểm ra file .xlsx
 *
 * Toàn bộ API ở đây đều yêu cầu token Giám thị — dùng chung authHeaders với ProctorDashboard.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Upload,
  FileSpreadsheet,
  FileText,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Copy,
  Check,
  Trash2,
  Send,
  BarChart3,
  Download,
  X,
  ClipboardList,
  RefreshCw,
} from "lucide-react";

import { API_BASE_URL } from "../config";

const STATUS_BADGE = {
  DRAFT: {
    label: "Nháp",
    className: "bg-amber-500/10 text-amber-700 border-amber-500/30",
  },
  PUBLISHED: {
    label: "Đã công bố",
    className: "bg-green-500/10 text-green-700 border-green-500/30",
  },
  CLOSED: {
    label: "Đã đóng",
    className: "bg-slate-500/10 text-slate-700 border-slate-500/30",
  },
};

/* ─────────────────────────────────────────────────────────
   Nút copy mã đề thi vào clipboard, kèm phản hồi trực quan
   ────────────────────────────────────────────────────────── */
function CopyCodeButton({ code }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* Trình duyệt chặn clipboard API (ít gặp) — bỏ qua, người dùng vẫn nhìn thấy mã để tự chép tay */
    }
  };

  return (
    <button
      onClick={handleCopy}
      title="Sao chép mã đề"
      className="p-1.5 rounded-lg hover:bg-bg-card-hover text-text-muted hover:text-accent-cyan transition-colors cursor-pointer"
    >
      {copied ? (
        <Check className="w-3.5 h-3.5 text-green-700" />
      ) : (
        <Copy className="w-3.5 h-3.5" />
      )}
    </button>
  );
}

/* ─────────────────────────────────────────────────────────
   Modal Công bố đề thi (Publish)
   ────────────────────────────────────────────────────────── */
function PublishModal({ exam, authHeaders, onClose, onPublished }) {
  const [durationMinutes, setDurationMinutes] = useState(45);
  const [passScore, setPassScore] = useState(5);
  const [shuffleQuestions, setShuffleQuestions] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE_URL}/exams/${exam.id}/publish`, {
        method: "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({
          duration_minutes: Number(durationMinutes),
          pass_score: Number(passScore),
          shuffle_questions: shuffleQuestions,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      onPublished(data);
    } catch (err) {
      setError(err.message || "Công bố đề thi thất bại");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title="Công bố đề thi" onClose={onClose} busy={submitting}>
      <div className="glass-card w-full max-w-md p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold text-text-primary">
            Công bố đề thi
          </h3>
          <button
            onClick={onClose}
            aria-label="Đóng hộp thoại"
            className="text-text-muted hover:text-text-primary cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <p className="text-sm text-text-secondary">
          <span className="font-mono font-semibold text-text-primary">
            {exam.exam_code}
          </span>{" "}
          — {exam.title}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-text-muted mb-1.5 uppercase tracking-wide">
              Thời gian làm bài (phút)
            </label>
            <input
              type="number"
              min={1}
              max={600}
              required
              value={durationMinutes}
              onChange={(e) => setDurationMinutes(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-bg-card border border-border-default text-text-primary
                         focus:outline-none focus:border-accent-cyan/60 focus:ring-1 focus:ring-accent-cyan/40"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-text-muted mb-1.5 uppercase tracking-wide">
              Điểm đạt (thang 10)
            </label>
            <input
              type="number"
              min={0}
              max={10}
              step={0.1}
              required
              value={passScore}
              onChange={(e) => setPassScore(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-bg-card border border-border-default text-text-primary
                         focus:outline-none focus:border-accent-cyan/60 focus:ring-1 focus:ring-accent-cyan/40"
            />
          </div>

          <label className="flex items-center gap-2.5 text-sm text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={shuffleQuestions}
              onChange={(e) => setShuffleQuestions(e.target.checked)}
              className="w-4 h-4 rounded accent-cyan-500"
            />
            Trộn thứ tự câu hỏi cho từng sinh viên
          </label>

          {error && (
            <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
              <AlertTriangle className="w-4 h-4 text-red-700 flex-shrink-0 mt-0.5" />
              <p className="text-red-700 text-sm">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full py-3 rounded-xl font-bold text-white bg-accent-cyan
                       hover:brightness-95 shadow-sm disabled:opacity-50
                       transition-all cursor-pointer flex items-center justify-center gap-2"
          >
            {submitting ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
            {submitting ? "Đang công bố..." : "Công bố ngay"}
          </button>
        </form>
      </div>
    </ModalShell>
  );
}

/* ─────────────────────────────────────────────────────────
   Modal Bảng điểm (Results) + Xuất Excel
   ────────────────────────────────────────────────────────── */
function ResultsModal({ exam, authHeaders, onClose }) {
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/exams/${exam.id}/results`, {
          headers: authHeaders,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        if (!cancelled) setResults(data);
      } catch (err) {
        if (!cancelled) setError(err.message || "Không tải được bảng điểm");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [exam.id, authHeaders]);

  const handleExport = async () => {
    setExporting(true);
    setExportError("");
    try {
      const res = await fetch(`${API_BASE_URL}/exams/${exam.id}/export`, {
        headers: authHeaders,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : `BangDiem_${exam.exam_code}.xlsx`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err.message || "Xuất Excel thất bại");
    } finally {
      setExporting(false);
    }
  };

  return (
    <ModalShell title="Bảng điểm" onClose={onClose} busy={exporting}>
      <div className="glass-card w-full max-w-3xl max-h-[85vh] flex flex-col p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-text-primary">Bảng điểm</h3>
            <p className="text-sm text-text-secondary">
              <span className="font-mono font-semibold text-text-primary">
                {exam.exam_code}
              </span>{" "}
              — {exam.title}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Đóng hộp thoại"
            className="text-text-muted hover:text-text-primary cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {loading ? (
          <div className="flex-1 flex items-center justify-center py-10">
            <Loader2 className="w-6 h-6 text-accent-cyan animate-spin" />
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
            <AlertTriangle className="w-4 h-4 text-red-700 flex-shrink-0 mt-0.5" />
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        ) : results.results.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center py-10 text-text-muted">
            <ClipboardList className="w-10 h-10 mb-3 opacity-30" />
            <p>Chưa có sinh viên nào nộp bài cho đề thi này</p>
          </div>
        ) : (
          <div className="flex-1 overflow-auto rounded-xl border border-border-default">
            <table className="w-full text-sm">
              <thead className="bg-bg-card sticky top-0">
                <tr>
                  {[
                    "Mã SV",
                    "Họ và tên",
                    "Điểm",
                    "Đúng/Tổng",
                    "Vi phạm",
                    "Trạng thái",
                  ].map((h) => (
                    <th
                      key={h}
                      className="px-4 py-3 text-left font-semibold text-text-secondary uppercase text-xs tracking-wide"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border-default">
                {results.results.map((r, idx) => (
                  <tr key={idx} className="hover:bg-bg-card-hover/40">
                    <td className="px-4 py-3 font-mono text-text-primary">
                      {r.student_id}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {r.student_name || "—"}
                    </td>
                    <td
                      className={`px-4 py-3 font-bold ${r.passed ? "text-green-700" : "text-red-700"}`}
                    >
                      {Number(r.total_score ?? 0).toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {r.correct_count}/{r.total_questions}
                    </td>
                    <td className="px-4 py-3">
                      {r.violation_count > 0 ? (
                        <span className="text-red-700 font-semibold">
                          {r.violation_count}
                        </span>
                      ) : (
                        <span className="text-text-muted">0</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-1 rounded-full text-xs font-semibold ${
                          r.passed
                            ? "bg-green-500/10 text-green-700"
                            : "bg-red-500/10 text-red-700"
                        }`}
                      >
                        {r.passed ? "Đạt" : "Không đạt"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {exportError && (
          <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
            <AlertTriangle className="w-4 h-4 text-red-700 flex-shrink-0 mt-0.5" />
            <p className="text-red-700 text-sm">{exportError}</p>
          </div>
        )}

        {!loading && !error && results?.results?.length > 0 && (
          <button
            onClick={handleExport}
            disabled={exporting}
            className="w-full py-3 rounded-xl font-bold text-white bg-accent-cyan
                       hover:brightness-95 shadow-sm disabled:opacity-50
                       transition-all cursor-pointer flex items-center justify-center gap-2"
          >
            {exporting ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            {exporting ? "Đang xuất..." : "Xuất bảng điểm Excel (.xlsx)"}
          </button>
        )}
      </div>
    </ModalShell>
  );
}

/* ─────────────────────────────────────────────────────────
   Panel Upload đề thi mới
   ────────────────────────────────────────────────────────── */
function UploadPanel({ authHeaders, teacherId, onClose, onUploaded }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [examCode, setExamCode] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(""); // string hoặc {message, errors}
  const [uploadSuccess, setUploadSuccess] = useState(null); // { exam, parse_errors }

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file || !title.trim()) return;

    setUploading(true);
    setUploadError("");
    setUploadSuccess(null);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title.trim());
    if (examCode.trim()) formData.append("exam_code", examCode.trim());
    if (teacherId) formData.append("created_by", teacherId);

    try {
      // LƯU Ý: không tự set 'Content-Type' — trình duyệt tự thêm boundary đúng cho multipart/form-data.
      // authHeaders chỉ chứa 'X-Proctor-Token' nên spread trực tiếp là an toàn.
      const res = await fetch(`${API_BASE_URL}/exams/upload`, {
        method: "POST",
        headers: authHeaders,
        body: formData,
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        // Trường hợp 422 (0 câu hợp lệ): backend trả detail dạng OBJECT {message, errors}, không phải string
        if (
          res.status === 422 &&
          data.detail &&
          typeof data.detail === "object"
        ) {
          setUploadError(data.detail);
        } else {
          setUploadError(
            typeof data.detail === "string"
              ? data.detail
              : `Upload thất bại (HTTP ${res.status})`,
          );
        }
        return;
      }

      setUploadSuccess(data); // { exam, parse_errors }
      onUploaded();
    } catch (err) {
      setUploadError(err.message || "Không thể kết nối máy chủ");
    } finally {
      setUploading(false);
    }
  };

  const resetForm = () => {
    setFile(null);
    setTitle("");
    setExamCode("");
    setUploadError("");
    setUploadSuccess(null);
  };

  return (
    <ModalShell title="Tải lên đề thi mới" onClose={onClose} busy={uploading}>
      <div className="glass-card w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold text-text-primary flex items-center gap-2">
            <Upload className="w-5 h-5 text-accent-cyan" /> Tải lên đề thi mới
          </h3>
          <button
            onClick={onClose}
            aria-label="Đóng hộp thoại"
            className="text-text-muted hover:text-text-primary cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {!uploadSuccess ? (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-text-muted mb-1.5 uppercase tracking-wide">
                Tên đề thi / học phần *
              </label>
              <input
                type="text"
                required
                placeholder="VD: Kiểm tra giữa kỳ"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl bg-bg-card border border-border-default text-text-primary
                           placeholder-text-muted focus:outline-none focus:border-accent-cyan/60 focus:ring-1 focus:ring-accent-cyan/40"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-text-muted mb-1.5 uppercase tracking-wide">
                Mã đề thi (tuỳ chọn — để trống sẽ tự sinh)
              </label>
              <input
                type="text"
                placeholder="VD: CSDL-DE01"
                value={examCode}
                onChange={(e) => setExamCode(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl bg-bg-card border border-border-default text-text-primary
                           placeholder-text-muted focus:outline-none focus:border-accent-cyan/60 focus:ring-1 focus:ring-accent-cyan/40"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-text-muted mb-1.5 uppercase tracking-wide">
                File đề thi (.xlsx hoặc .docx theo mẫu) *
              </label>
              <label
                className="flex flex-col items-center justify-center gap-2 w-full py-8 rounded-xl border-2 border-dashed
                           border-border-default hover:border-accent-cyan/50 cursor-pointer transition-colors bg-bg-card/50"
              >
                <input
                  type="file"
                  accept=".xlsx,.docx"
                  required
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  className="sr-only"
                />
                {file ? (
                  <>
                    {file.name.endsWith(".xlsx") ? (
                      <FileSpreadsheet className="w-8 h-8 text-green-700" />
                    ) : (
                      <FileText className="w-8 h-8 text-blue-700" />
                    )}
                    <span className="text-sm text-text-primary font-medium">
                      {file.name}
                    </span>
                    <span className="text-xs text-text-muted">
                      Bấm để chọn file khác
                    </span>
                  </>
                ) : (
                  <>
                    <Upload className="w-8 h-8 text-text-muted" />
                    <span className="text-sm text-text-secondary">
                      Bấm để chọn file .xlsx hoặc .docx
                    </span>
                  </>
                )}
              </label>
            </div>

            {uploadError && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 space-y-2">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-red-700 flex-shrink-0 mt-0.5" />
                  <p className="text-red-700 text-sm">
                    {typeof uploadError === "string"
                      ? uploadError
                      : uploadError.message}
                  </p>
                </div>
                {typeof uploadError === "object" &&
                  Array.isArray(uploadError.errors) && (
                    <ul className="text-xs text-red-700/80 space-y-1 pl-6 list-disc">
                      {uploadError.errors.slice(0, 10).map((e, i) => (
                        <li key={i}>
                          [{e.location}] {e.message}
                        </li>
                      ))}
                    </ul>
                  )}
              </div>
            )}

            <button
              type="submit"
              disabled={uploading || !file || !title.trim()}
              className="w-full py-3 rounded-xl font-bold text-white bg-accent-cyan
                         hover:brightness-95 shadow-sm
                         disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer
                         flex items-center justify-center gap-2"
            >
              {uploading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" /> Đang xử lý
                  file...
                </>
              ) : (
                "Tải lên & Đọc đề thi"
              )}
            </button>
          </form>
        ) : (
          /* ── Kết quả sau khi upload thành công: preview số câu hợp lệ + lỗi (nếu có) ── */
          <div className="space-y-4">
            <div className="flex items-start gap-3 bg-green-500/10 border border-green-500/30 rounded-xl px-4 py-3">
              <CheckCircle2 className="w-5 h-5 text-green-700 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-green-700 font-semibold text-sm">
                  Đã tạo đề nháp với {uploadSuccess.exam.total_questions} câu
                  hỏi hợp lệ
                </p>
                <p className="text-text-secondary text-sm mt-1">
                  Mã đề:{" "}
                  <span className="font-mono font-bold text-text-primary">
                    {uploadSuccess.exam.exam_code}
                  </span>
                </p>
              </div>
            </div>

            {uploadSuccess.parse_errors.length > 0 && (
              <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 space-y-2">
                <p className="text-amber-700 font-semibold text-sm flex items-center gap-1.5">
                  <AlertTriangle className="w-4 h-4" />{" "}
                  {uploadSuccess.parse_errors.length} câu bị bỏ qua do lỗi:
                </p>
                <ul className="text-xs text-amber-700/90 space-y-1 pl-5 list-disc max-h-40 overflow-y-auto">
                  {uploadSuccess.parse_errors.map((e, i) => (
                    <li key={i}>
                      [{e.location}] {e.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-xs text-text-muted leading-relaxed">
              Đề thi đang ở trạng thái{" "}
              <span className="font-semibold text-amber-700">Nháp</span> — sinh
              viên CHƯA thể truy cập. Vào danh sách đề thi và bấm "Công bố" khi
              sẵn sàng mở cho sinh viên làm bài.
            </p>

            <div className="flex gap-3">
              <button
                onClick={resetForm}
                className="flex-1 py-2.5 rounded-xl font-semibold text-text-secondary bg-bg-card
                           border border-border-default hover:bg-bg-card-hover transition-all cursor-pointer"
              >
                Tải đề khác
              </button>
              <button
                onClick={onClose}
                className="flex-1 py-2.5 rounded-xl font-bold text-white bg-accent-cyan
                           hover:brightness-95 transition-all cursor-pointer"
              >
                Xong
              </button>
            </div>
          </div>
        )}
      </div>
    </ModalShell>
  );
}

/* ─────────────────────────────────────────────────────────
   Component chính: ExamManagement
   ────────────────────────────────────────────────────────── */
export default function ExamManagement({ authToken, teacherId }) {
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const [publishingExam, setPublishingExam] = useState(null);
  const [resultsExam, setResultsExam] = useState(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [deleteError, setDeleteError] = useState("");

  const authHeaders = useMemo(
    () => ({ "X-Proctor-Token": authToken || "" }),
    [authToken],
  );
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const visibleExams = exams.filter(
    (exam) =>
      (!statusFilter || exam.status === statusFilter) &&
      `${exam.title} ${exam.exam_code}`
        .toLocaleLowerCase("vi")
        .includes(query.trim().toLocaleLowerCase("vi")),
  );

  const fetchExams = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/exams`, {
        headers: authHeaders,
      });
      if (res.status === 401)
        throw new Error("Token không hợp lệ — vui lòng đăng xuất và nhập lại");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setExams(data);
      setError("");
    } catch (err) {
      setError(err.message || "Không thể tải danh sách đề thi");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authHeaders]);

  useEffect(() => {
    fetchExams();
  }, [fetchExams]);

  const handleDelete = async (examId) => {
    setDeletingId(examId);
    setDeleteError("");
    try {
      const res = await fetch(`${API_BASE_URL}/exams/${examId}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setExams((prev) => prev.filter((e) => e.id !== examId));
      setConfirmDeleteId(null);
    } catch (err) {
      setDeleteError(err.message || "Xóa đề thi thất bại");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-5">
      {/* Thanh công cụ trên cùng */}
      <div className="glass-card p-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-text-primary flex items-center gap-2">
            <ClipboardList className="w-5 h-5 text-accent-cyan" /> Quản lý Đề
            thi
          </h2>
          <p className="text-sm text-text-muted mt-0.5">
            Upload đề thi trắc nghiệm, công bố cho sinh viên, xem bảng điểm &
            xuất Excel
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={fetchExams}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold
                       bg-bg-card border border-border-default text-text-secondary
                       hover:bg-bg-card-hover hover:text-text-primary transition-all cursor-pointer"
          >
            <RefreshCw className="w-4 h-4" /> Làm mới
          </button>
          <button
            onClick={() => setShowUpload(true)}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold text-white
                       bg-accent-cyan hover:brightness-95
                       shadow-sm transition-all cursor-pointer"
          >
            <Upload className="w-4 h-4" /> Tải lên đề thi mới
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-2xl p-4">
          <AlertTriangle className="w-5 h-5 text-red-700 flex-shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
          <button
            onClick={fetchExams}
            className="ml-auto text-sm text-red-700 underline hover:text-red-700 cursor-pointer"
          >
            Thử lại
          </button>
        </div>
      )}

      {deleteError && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-2xl p-4">
          <AlertTriangle className="w-5 h-5 text-red-700 flex-shrink-0" />
          <p className="text-sm text-red-700">{deleteError}</p>
        </div>
      )}

      <div className="exam-filters">
        <div className="exam-search">
          <label htmlFor="exam-search">Tìm đề thi</label>
          <input
            id="exam-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Tìm theo tên hoặc mã đề…"
          />
        </div>
        <div>
          <label htmlFor="exam-status">Trạng thái</label>
          <select
            id="exam-status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">Tất cả trạng thái</option>
            <option value="DRAFT">Nháp</option>
            <option value="PUBLISHED">Đã công bố</option>
            <option value="CLOSED">Đã đóng</option>
          </select>
        </div>
        <span>
          {visibleExams.length} / {exams.length} đề thi
        </span>
      </div>
      {/* Danh sách đề thi */}
      {loading ? (
        <div className="glass-card flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 text-accent-cyan animate-spin" />
          <span className="ml-3 text-text-secondary">
            Đang tải danh sách đề thi...
          </span>
        </div>
      ) : visibleExams.length === 0 ? (
        <div className="glass-card flex flex-col items-center justify-center py-20 text-text-muted">
          <ClipboardList className="w-16 h-16 mb-4 opacity-20" />
          <p className="text-lg font-medium">
            {exams.length
              ? "Không tìm thấy đề thi phù hợp"
              : "Chưa có đề thi nào"}
          </p>
          <p className="text-sm mt-1">
            {exams.length
              ? "Thử từ khóa khác hoặc chọn tất cả trạng thái."
              : 'Bấm "Tải lên đề thi mới" để bắt đầu'}
          </p>
        </div>
      ) : (
        <div className="glass-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-bg-card">
              <tr>
                {[
                  "Mã đề",
                  "Tên đề thi",
                  "Số câu",
                  "Thời gian",
                  "Trạng thái",
                  "Thao tác",
                ].map((h) => (
                  <th
                    key={h}
                    className="px-5 py-3.5 text-left font-semibold text-text-secondary uppercase text-xs tracking-wide"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border-default">
              {visibleExams.map((exam) => {
                const badge = STATUS_BADGE[exam.status] || STATUS_BADGE.DRAFT;
                return (
                  <tr
                    key={exam.id}
                    className="hover:bg-bg-card-hover/40 transition-colors"
                  >
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono font-semibold text-text-primary">
                          {exam.exam_code}
                        </span>
                        <CopyCodeButton code={exam.exam_code} />
                      </div>
                    </td>
                    <td className="px-5 py-4 text-text-secondary max-w-xs truncate">
                      {exam.title}
                    </td>
                    <td className="px-5 py-4 text-text-secondary">
                      {exam.total_questions}
                    </td>
                    <td className="px-5 py-4 text-text-secondary">
                      {exam.duration_minutes
                        ? `${exam.duration_minutes} phút`
                        : "—"}
                    </td>
                    <td className="px-5 py-4">
                      <span
                        className={`px-2.5 py-1 rounded-full text-xs font-semibold border ${badge.className}`}
                      >
                        {badge.label}
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        {exam.status === "DRAFT" && (
                          <button
                            onClick={() => setPublishingExam(exam)}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                                       bg-cyan-500/10 text-accent-cyan border border-cyan-500/30
                                       hover:bg-cyan-500/20 transition-all cursor-pointer"
                          >
                            <Send className="w-3.5 h-3.5" /> Công bố
                          </button>
                        )}
                        {exam.status === "PUBLISHED" && (
                          <button
                            onClick={() => setResultsExam(exam)}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                                       bg-green-500/10 text-green-700 border border-green-500/30
                                       hover:bg-green-500/20 transition-all cursor-pointer"
                          >
                            <BarChart3 className="w-3.5 h-3.5" /> Xem điểm
                          </button>
                        )}

                        {confirmDeleteId === exam.id ? (
                          <div className="flex items-center gap-1.5">
                            <button
                              onClick={() => handleDelete(exam.id)}
                              disabled={deletingId === exam.id}
                              className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-red-600 text-white hover:bg-red-500 cursor-pointer disabled:opacity-50"
                            >
                              {deletingId === exam.id ? "..." : "Xác nhận"}
                            </button>
                            <button
                              onClick={() => setConfirmDeleteId(null)}
                              className="px-2.5 py-1.5 rounded-lg text-xs font-medium bg-bg-card border border-border-default text-text-secondary cursor-pointer"
                            >
                              Hủy
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setConfirmDeleteId(exam.id)}
                            title="Xóa đề thi"
                            className="p-1.5 rounded-lg text-text-muted hover:text-red-700 hover:bg-red-500/10 transition-colors cursor-pointer"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Modals ── */}
      {showUpload && (
        <UploadPanel
          authHeaders={authHeaders}
          teacherId={teacherId}
          onClose={() => setShowUpload(false)}
          onUploaded={fetchExams}
        />
      )}
      {publishingExam && (
        <PublishModal
          exam={publishingExam}
          authHeaders={authHeaders}
          onClose={() => setPublishingExam(null)}
          onPublished={() => {
            setPublishingExam(null);
            fetchExams();
          }}
        />
      )}
      {resultsExam && (
        <ResultsModal
          exam={resultsExam}
          authHeaders={authHeaders}
          onClose={() => setResultsExam(null)}
        />
      )}
    </div>
  );
}
