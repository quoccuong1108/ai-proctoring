/**
 * EduShield AI — Quản lý & Duyệt Thí sinh vào phòng thi
 * Giai đoạn C: Giảng viên xem danh sách xin vào thi, duyệt / từ chối / thu hồi quyền thi.
 */

import { Fragment, useState, useEffect, useCallback, useRef } from "react";
import {
  Users,
  CheckCircle,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Search,
  Filter,
  Clock,
  ShieldAlert,
  Laptop,
  Smartphone,
  Globe,
} from "lucide-react";
import { API_BASE_URL } from "../config";
import AuthedImage from "./AuthedImage";

function getSavedEnrollmentView() {
  try {
    return JSON.parse(sessionStorage.getItem("teacher_enrollment_view") || "{}");
  } catch {
    sessionStorage.removeItem("teacher_enrollment_view");
    return {};
  }
}

export default function EnrollmentApproval({ authToken, onPendingCountChange }) {
  const [savedView] = useState(getSavedEnrollmentView);
  const [exams, setExams] = useState([]);
  const [selectedExamId, setSelectedExamId] = useState(savedView.examId || null);
  const [selectedSubject, setSelectedSubject] = useState(savedView.subject || "");
  const [enrollments, setEnrollments] = useState([]);
  const [loadingExams, setLoadingExams] = useState(true);
  const [loadingEnrollments, setLoadingEnrollments] = useState(false);
  const [error, setError] = useState("");
  const [filterStatus, setFilterStatus] = useState(savedView.filterStatus || "ALL");
  const [searchQuery, setSearchQuery] = useState(savedView.searchQuery || "");
  const [actionLoadingId, setActionLoadingId] = useState(null);

  // Modal từ chối
  const [rejectModalEnrollment, setRejectModalEnrollment] = useState(null);
  const [rejectReason, setRejectReason] = useState("");
  const [historyEnrollment, setHistoryEnrollment] = useState(null);
  const [violationHistory, setViolationHistory] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState("");

  const pollTimerRef = useRef(null);

  useEffect(() => {
    sessionStorage.setItem(
      "teacher_enrollment_view",
      JSON.stringify({ examId: selectedExamId, subject: selectedSubject, filterStatus, searchQuery }),
    );
  }, [selectedExamId, selectedSubject, filterStatus, searchQuery]);

  // Headers xác thực
  const getHeaders = useCallback(() => ({
    "Content-Type": "application/json",
    Authorization: `Bearer ${authToken || ""}`,
  }), [authToken]);

  // Tải danh sách đề thi của giảng viên
  const fetchExams = useCallback(async () => {
    try {
      setLoadingExams(true);
      const res = await fetch(`${API_BASE_URL}/exams`, { headers: getHeaders() });
      if (!res.ok) throw new Error(`Lỗi tải danh sách đề (HTTP ${res.status})`);
      const data = await res.json();
      setExams(data);
      if (data.length > 0) {
        const savedExam = data.find((exam) => exam.id === selectedExamId);
        const initialExam = savedExam || data[0];
        setSelectedExamId(initialExam.id);
        setSelectedSubject(initialExam.subject || "Chưa phân môn");
      } else {
        setSelectedExamId(null);
        setSelectedSubject("");
      }
    } catch (err) {
      setError(err.message || "Không thể tải danh sách đề thi");
    } finally {
      setLoadingExams(false);
    }
  }, [getHeaders, selectedExamId]);

  // Tải danh sách enrollments của đề được chọn
  const fetchEnrollments = useCallback(async (isPolling = false) => {
    if (!selectedExamId) return;
    try {
      if (!isPolling) setLoadingEnrollments(true);
      const res = await fetch(
        `${API_BASE_URL}/exams/${selectedExamId}/enrollments`,
        { headers: getHeaders() }
      );
      if (!res.ok) throw new Error(`Lỗi tải danh sách thí sinh (HTTP ${res.status})`);
      const data = await res.json();
      setEnrollments(data);

      const pendingRes = await fetch(
        `${API_BASE_URL}/exams/enrollments?status=PENDING`,
        { headers: getHeaders() },
      );
      if (!pendingRes.ok) {
        throw new Error(`Lỗi tải số yêu cầu đang chờ (HTTP ${pendingRes.status})`);
      }
      const pendingData = await pendingRes.json();
      if (onPendingCountChange) onPendingCountChange(pendingData.length);
    } catch (err) {
      if (!isPolling) setError(err.message || "Không thể tải danh sách thí sinh");
    } finally {
      if (!isPolling) setLoadingEnrollments(false);
    }
  }, [selectedExamId, getHeaders, onPendingCountChange]);

  const subjects = [...new Set(exams.map((exam) => exam.subject || "Chưa phân môn"))];
  const subjectExams = exams.filter(
    (exam) => (exam.subject || "Chưa phân môn") === selectedSubject,
  );

  useEffect(() => {
    fetchExams();
  }, [fetchExams]);

  useEffect(() => {
    fetchEnrollments();
    // Polling mỗi 4 giây
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(() => {
      fetchEnrollments(true);
    }, 4000);

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [fetchEnrollments]);

  // Duyệt thí sinh
  const handleApprove = async (enrollmentId) => {
    try {
      setActionLoadingId(enrollmentId);
      const res = await fetch(
        `${API_BASE_URL}/exams/${selectedExamId}/enrollments/${enrollmentId}/approve`,
        { method: "POST", headers: getHeaders() }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Không thể duyệt thí sinh");
      }
      await fetchEnrollments(true);
    } catch (err) {
      alert(`Lỗi: ${err.message}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleApproveAll = async () => {
    if (!selectedExamId || pendingCount === 0) return;
    if (!window.confirm(`Duyệt tất cả ${pendingCount} yêu cầu đang chờ của đề này?`)) return;
    try {
      setActionLoadingId("all");
      const res = await fetch(
        `${API_BASE_URL}/exams/${selectedExamId}/enrollments/approve-all`,
        { method: "POST", headers: getHeaders() },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `Không thể duyệt tất cả (HTTP ${res.status})`);
      }
      await fetchEnrollments(true);
    } catch (err) {
      alert(`Lỗi: ${err.message}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  // Mở modal từ chối
  const openRejectModal = (enrollment) => {
    setRejectModalEnrollment(enrollment);
    setRejectReason("Không đúng thông tin đăng ký hoặc không thuộc danh sách phòng thi.");
  };

  const handleViewHistory = async (enrollment) => {
    setHistoryEnrollment(enrollment);
    setViolationHistory([]);
    setHistoryError("");
    setLoadingHistory(true);
    try {
      const query = new URLSearchParams({
        student_id: enrollment.student_id,
        limit: "100",
      });
      const res = await fetch(`${API_BASE_URL}/violations?${query}`, {
        headers: getHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `Không thể tải lịch sử (HTTP ${res.status})`);
      }
      setViolationHistory(data);
    } catch (err) {
      setHistoryError(err.message || "Không thể tải lịch sử vi phạm");
    } finally {
      setLoadingHistory(false);
    }
  };

  // Xác nhận từ chối
  const handleConfirmReject = async () => {
    if (!rejectModalEnrollment) return;
    try {
      setActionLoadingId(rejectModalEnrollment.id);
      const res = await fetch(
        `${API_BASE_URL}/exams/${selectedExamId}/enrollments/${rejectModalEnrollment.id}/reject`,
        {
          method: "POST",
          headers: getHeaders(),
          body: JSON.stringify({ reason: rejectReason }),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Không thể từ chối thí sinh");
      }
      setRejectModalEnrollment(null);
      await fetchEnrollments(true);
    } catch (err) {
      alert(`Lỗi: ${err.message}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  // Thu hồi quyền thi (đình chỉ)
  const handleRevoke = async (enrollmentId) => {
    if (!window.confirm("Bạn có chắc chắn muốn thu hồi quyền thi của thí sinh này?")) return;
    try {
      setActionLoadingId(enrollmentId);
      const res = await fetch(
        `${API_BASE_URL}/exams/${selectedExamId}/enrollments/${enrollmentId}/revoke`,
        {
          method: "POST",
          headers: getHeaders(),
          body: JSON.stringify({ reason: "Giám thị đình chỉ quyền thi do vi phạm quy chế." }),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Không thể đình chỉ thí sinh");
      }
      await fetchEnrollments(true);
    } catch (err) {
      alert(`Lỗi: ${err.message}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  // Helper phân loại thiết bị
  const renderDeviceBadge = (deviceInfo) => {
    if (!deviceInfo) return <span className="text-text-muted text-xs">—</span>;
    const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(deviceInfo);
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-md bg-bg-card border border-border-default text-text-secondary max-w-[180px] truncate" title={deviceInfo}>
        {isMobile ? <Smartphone className="w-3 h-3 text-amber-600" /> : <Laptop className="w-3 h-3 text-blue-600" />}
        <span className="truncate">{deviceInfo.slice(0, 30)}...</span>
      </span>
    );
  };

  // Lọc dữ liệu hiển thị
  const filteredEnrollments = enrollments.filter((item) => {
    if (filterStatus !== "ALL" && item.status !== filterStatus) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchId = (item.student_id || "").toLowerCase().includes(q);
      const matchName = (item.student_name || "").toLowerCase().includes(q);
      if (!matchId && !matchName) return false;
    }
    return true;
  });

  const pendingCount = enrollments.filter((e) => e.status === "PENDING").length;
  const approvedCount = enrollments.filter((e) => e.status === "APPROVED").length;
  const rejectedCount = enrollments.filter((e) => e.status === "REJECTED").length;
  const revokedCount = enrollments.filter((e) => e.status === "REVOKED").length;

  const selectedExam = exams.find((e) => e.id === selectedExamId);

  return (
    <div className="space-y-6">
      {/* Thanh chọn đề thi & Trạng thái */}
      <div className="glass-card p-5 space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-accent-cyan/15 border border-cyan-500/30 flex items-center justify-center text-accent-cyan font-bold">
              <Users className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-text-primary">Duyệt & Quản lý Thí sinh vào phòng thi</h2>
              <p className="text-xs text-text-muted">Kiểm soát danh sách thí sinh xin vào thi theo thời gian thực</p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full sm:w-auto">
            <select
              value={selectedSubject}
              onChange={(e) => {
                const subject = e.target.value;
                setSelectedSubject(subject);
                const nextExam = exams.find(
                  (exam) => (exam.subject || "Chưa phân môn") === subject,
                );
                setSelectedExamId(nextExam?.id || null);
              }}
              className="min-h-11 px-3 rounded-xl bg-bg-card border border-border-default text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-cyan"
              disabled={loadingExams || subjects.length === 0}
            >
              {subjects.length === 0 && <option value="">Chưa có môn học</option>}
              {subjects.map((subject) => (
                <option key={subject} value={subject}>{subject}</option>
              ))}
            </select>
            <select
              value={selectedExamId || ""}
              onChange={(e) => setSelectedExamId(Number(e.target.value))}
              className="min-h-11 px-3 rounded-xl bg-bg-card border border-border-default text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-cyan"
              disabled={loadingExams}
            >
              {subjectExams.length === 0 && <option value="">Chưa có đề thi nào</option>}
              {subjectExams.map((ex) => (
                <option key={ex.id} value={ex.id}>
                  {ex.title} ({ex.exam_code})
                </option>
              ))}
            </select>
            <button
              onClick={handleApproveAll}
              disabled={!pendingCount || actionLoadingId === "all"}
              className="min-h-11 px-4 rounded-xl text-sm font-bold bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 transition-colors cursor-pointer whitespace-nowrap"
            >
              {actionLoadingId === "all" ? "Đang duyệt..." : `Duyệt tất cả (${pendingCount})`}
            </button>

            <button
              onClick={() => fetchEnrollments(false)}
              disabled={loadingEnrollments}
              className="p-2 rounded-xl bg-bg-card border border-border-default hover:bg-bg-card-hover transition-colors text-text-secondary"
              title="Làm mới danh sách"
            >
              <RefreshCw className={`w-4 h-4 ${loadingEnrollments ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {selectedExam && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 border-t border-border-default">
            <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-between">
              <div>
                <p className="text-xs text-amber-700 font-semibold uppercase">Đang chờ duyệt</p>
                <p className="text-2xl font-bold text-amber-700">{pendingCount}</p>
              </div>
              <Clock className="w-6 h-6 text-amber-700/60" />
            </div>

            <div className="p-3 rounded-xl bg-green-500/10 border border-green-500/30 flex items-center justify-between">
              <div>
                <p className="text-xs text-green-700 font-semibold uppercase">Đã duyệt</p>
                <p className="text-2xl font-bold text-green-700">{approvedCount}</p>
              </div>
              <CheckCircle className="w-6 h-6 text-green-700/60" />
            </div>

            <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 flex items-center justify-between">
              <div>
                <p className="text-xs text-red-700 font-semibold uppercase">Từ chối</p>
                <p className="text-2xl font-bold text-red-700">{rejectedCount}</p>
              </div>
              <XCircle className="w-6 h-6 text-red-700/60" />
            </div>

            <div className="p-3 rounded-xl bg-slate-500/10 border border-slate-500/30 flex items-center justify-between">
              <div>
                <p className="text-xs text-slate-700 font-semibold uppercase">Bị đình chỉ</p>
                <p className="text-2xl font-bold text-slate-700">{revokedCount}</p>
              </div>
              <ShieldAlert className="w-6 h-6 text-slate-700/60" />
            </div>
          </div>
        )}
      </div>

      {/* Bộ lọc và tìm kiếm */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Tìm theo mã SV hoặc họ tên..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-2 rounded-xl bg-bg-card border border-border-default text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-cyan"
          />
        </div>

        <div className="flex items-center gap-1.5 self-start sm:self-auto overflow-x-auto w-full sm:w-auto">
          <Filter className="w-4 h-4 text-text-muted mr-1 hidden sm:inline-block" />
          {[
            { id: "ALL", label: "Tất cả" },
            { id: "PENDING", label: `Chờ duyệt (${pendingCount})` },
            { id: "APPROVED", label: "Đã duyệt" },
            { id: "REJECTED", label: "Từ chối" },
            { id: "REVOKED", label: "Đình chỉ" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setFilterStatus(tab.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
                filterStatus === tab.id
                  ? "bg-accent-cyan text-white shadow-sm"
                  : "bg-bg-card text-text-secondary border border-border-default hover:bg-bg-card-hover"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-700 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Bảng danh sách thí sinh */}
      <div className="glass-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-bg-card/70 border-b border-border-default text-xs uppercase tracking-wider text-text-muted">
              <tr>
                <th className="py-3.5 px-4 font-semibold">Mã SV</th>
                <th className="py-3.5 px-4 font-semibold">Họ & Tên</th>
                <th className="py-3.5 px-4 font-semibold">Môn / Đề</th>
                <th className="py-3.5 px-4 font-semibold">Thiết bị & IP</th>
                <th className="py-3.5 px-4 font-semibold">Thời gian xin vào</th>
                <th className="py-3.5 px-4 font-semibold">Trạng thái</th>
                <th className="py-3.5 px-4 font-semibold text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-default">
              {filteredEnrollments.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-text-muted">
                    {loadingEnrollments ? "Đang tải dữ liệu..." : "Chưa có yêu cầu nào phù hợp."}
                  </td>
                </tr>
              ) : (
                filteredEnrollments.map((item) => (
                  <Fragment key={item.id}>
                  <tr className="hover:bg-bg-card-hover/40 transition-colors">
                    <td className="py-3.5 px-4 font-mono font-bold text-text-primary">
                      {item.student_id}
                    </td>
                    <td className="py-3.5 px-4 text-text-primary">
                      {item.student_name || "—"}
                    </td>
                    <td className="py-3.5 px-4 text-xs text-text-secondary">
                      <span className="block font-semibold text-text-primary">
                        {selectedExam?.subject || "Chưa phân môn"}
                      </span>
                      <span>{selectedExam?.title || "Đề thi"}</span>
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="flex flex-col gap-1">
                        {renderDeviceBadge(item.device_info)}
                        {item.ip && (
                          <span className="inline-flex items-center gap-1 text-[11px] text-text-muted">
                            <Globe className="w-3 h-3" /> {item.ip}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-xs text-text-secondary whitespace-nowrap">
                      {item.requested_at
                        ? new Date(item.requested_at).toLocaleTimeString("vi-VN", {
                            timeZone: "Asia/Ho_Chi_Minh",
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          })
                        : "—"}
                    </td>
                    <td className="py-3.5 px-4">
                      {item.status === "PENDING" && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-700 border border-amber-500/30 animate-pulse">
                          <Clock className="w-3 h-3" /> Chờ duyệt
                        </span>
                      )}
                      {item.status === "APPROVED" && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-green-500/10 text-green-700 border border-green-500/30">
                          <CheckCircle className="w-3 h-3" /> Đã duyệt
                        </span>
                      )}
                      {item.status === "REJECTED" && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-red-500/10 text-red-700 border border-red-500/30" title={item.reject_reason || "Bị từ chối"}>
                          <XCircle className="w-3 h-3" /> Từ chối
                        </span>
                      )}
                      {item.status === "REVOKED" && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-700 border border-slate-500/30" title={item.reject_reason || "Bị đình chỉ"}>
                          <ShieldAlert className="w-3 h-3" /> Đình chỉ
                        </span>
                      )}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => handleViewHistory(item)}
                          className="px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-amber-500/10 text-amber-700 border border-amber-500/30 hover:bg-amber-500/20 transition-colors cursor-pointer flex items-center gap-1"
                          title="Xem lịch sử vi phạm trước khi quyết định"
                        >
                          <AlertTriangle className="w-3.5 h-3.5" /> Lịch sử
                        </button>
                        {item.status === "PENDING" && (
                          <>
                            <button
                              onClick={() => handleApprove(item.id)}
                              disabled={actionLoadingId === item.id}
                              className="px-3 py-1.5 rounded-lg text-xs font-bold bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 transition-colors cursor-pointer flex items-center gap-1 shadow-sm"
                            >
                              <CheckCircle className="w-3.5 h-3.5" /> Duyệt
                            </button>
                            <button
                              onClick={() => openRejectModal(item)}
                              disabled={actionLoadingId === item.id}
                              className="px-3 py-1.5 rounded-lg text-xs font-bold bg-red-500/15 text-red-700 border border-red-500/30 hover:bg-red-500/25 disabled:opacity-50 transition-colors cursor-pointer flex items-center gap-1"
                            >
                              <XCircle className="w-3.5 h-3.5" /> Từ chối
                            </button>
                          </>
                        )}
                        {item.status === "APPROVED" && (
                          <button
                            onClick={() => handleRevoke(item.id)}
                            disabled={actionLoadingId === item.id}
                            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-500/15 text-slate-700 border border-slate-500/30 hover:bg-red-500/20 hover:text-red-700 disabled:opacity-50 transition-colors cursor-pointer flex items-center gap-1"
                            title="Đình chỉ quyền thi của thí sinh này"
                          >
                            <ShieldAlert className="w-3.5 h-3.5" /> Đình chỉ
                          </button>
                        )}
                        {item.status === "REJECTED" && (
                          <button
                            onClick={() => handleApprove(item.id)}
                            disabled={actionLoadingId === item.id}
                            className="px-2.5 py-1 rounded-lg text-xs font-semibold text-text-muted hover:text-green-700 transition-colors"
                            title="Xem xét và duyệt lại"
                          >
                            Duyệt lại
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {item.violation_summary && (
                    <tr className="bg-bg-card/40">
                      <td colSpan={7} className="px-4 py-3">
                        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                          <div className="min-w-48 text-xs text-text-secondary">
                            <strong className="text-text-primary">
                              Lịch sử vi phạm: {item.violation_summary.total || 0}
                            </strong>
                            <div className="mt-1">
                              {Object.entries(item.violation_summary.by_type || {})
                                .map(([type, count]) => `${type}: ${count}`)
                                .join(" · ") || "Chưa ghi nhận"}
                            </div>
                            {item.violation_summary.latest_at && (
                              <div className="mt-1 text-text-muted">
                                Gần nhất: {new Date(item.violation_summary.latest_at).toLocaleString("vi-VN")}
                              </div>
                            )}
                          </div>
                          <div className="flex gap-2 overflow-x-auto">
                            {(item.violation_summary.recent_images || []).slice(0, 5).map((image) => (
                              <div key={image.id} className="flex-shrink-0 space-y-1">
                                <AuthedImage
                                  url={image.image_url}
                                  token={authToken}
                                  alt={`Ảnh vi phạm ${image.violation_type}`}
                                  className="w-16 h-16 rounded-lg object-cover"
                                />
                                <p className="max-w-16 truncate text-[10px] text-text-muted">
                                  {image.violation_type}
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal xác nhận từ chối */}
      {rejectModalEnrollment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="glass-card w-full max-w-md p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-red-500/15 border border-red-500/30 flex items-center justify-center text-red-700">
                <XCircle className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-text-primary">Từ chối thí sinh</h3>
                <p className="text-xs text-text-muted">
                  {rejectModalEnrollment.student_name} ({rejectModalEnrollment.student_id})
                </p>
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-text-secondary uppercase">
                Lý do từ chối
              </label>
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 rounded-xl bg-bg-card border border-border-default text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-red-500"
                placeholder="Nhập lý do gửi đến thí sinh..."
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={() => setRejectModalEnrollment(null)}
                className="px-4 py-2 rounded-xl text-sm font-semibold text-text-secondary hover:bg-bg-card-hover transition-colors cursor-pointer"
              >
                Hủy
              </button>
              <button
                onClick={handleConfirmReject}
                disabled={actionLoadingId === rejectModalEnrollment.id}
                className="px-4 py-2 rounded-xl text-sm font-bold bg-red-600 text-white hover:bg-red-700 transition-colors cursor-pointer shadow-sm"
              >
                Xác nhận từ chối
              </button>
            </div>
          </div>
        </div>
      )}

      {historyEnrollment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="glass-card w-full max-w-2xl max-h-[85dvh] overflow-hidden flex flex-col shadow-2xl">
            <div className="p-5 border-b border-border-default flex items-start justify-between gap-4">
              <div>
                <h3 className="text-base font-bold text-text-primary">
                  Lịch sử vi phạm
                </h3>
                <p className="text-xs text-text-muted mt-1">
                  {historyEnrollment.student_name} ({historyEnrollment.student_id}) ·{" "}
                  {selectedExam?.title}
                </p>
              </div>
              <button
                onClick={() => setHistoryEnrollment(null)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-border-default text-text-secondary hover:bg-bg-card-hover"
              >
                Đóng
              </button>
            </div>
            <div className="p-5 overflow-y-auto space-y-3">
              {loadingHistory ? (
                <p className="text-sm text-text-muted">Đang tải lịch sử...</p>
              ) : historyError ? (
                <p className="text-sm text-red-700">{historyError}</p>
              ) : violationHistory.length === 0 ? (
                <p className="text-sm text-text-muted">
                  Chưa ghi nhận vi phạm nào của sinh viên này.
                </p>
              ) : (
                <>
                  <p className="text-xs text-text-muted">
                    Hiển thị tối đa {violationHistory.length} bản ghi gần nhất.
                  </p>
                  <ul className="divide-y divide-border-default">
                    {violationHistory.map((violation) => (
                      <li key={violation.id} className="py-3 flex items-start justify-between gap-4">
                        <div>
                          <p className="text-sm font-semibold text-text-primary">
                            {violation.violation_type}
                          </p>
                          <p className="text-xs text-text-muted mt-1">
                            {violation.exam_id
                              ? `Đề thi #${violation.exam_id}`
                              : "Đề thi không xác định"}
                          </p>
                        </div>
                        <time className="text-xs text-text-secondary whitespace-nowrap">
                          {violation.captured_at
                            ? new Date(violation.captured_at).toLocaleString("vi-VN")
                            : "Không rõ thời gian"}
                        </time>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
