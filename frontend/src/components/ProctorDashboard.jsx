/**
 * EduShield AI — Proctor Dashboard
 *
 * Màn hình Giám thị:
 *   1. Đọc dữ liệu vi phạm từ API GET /api/violations
 *   2. Hiển thị bảng nhật ký vi phạm kèm thumbnail ảnh snapshot
 *   3. Tính năng xóa ảnh sớm (Manual Delete) qua DELETE /api/violations/{id}/image
 *   4. Thống kê tổng hợp từ GET /api/violations/stats
 *   5. Auto-refresh mỗi 10 giây
 */

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Shield,
  AlertTriangle,
  CheckCircle2,
  Trash2,
  RefreshCw,
  Eye,
  EyeOff,
  Smartphone,
  Users,
  CameraOff,
  Search,
  Filter,
  X,
  BarChart3,
  Clock,
  Image as ImageIcon,
  ChevronDown,
  XCircle,
  MonitorCheck,
  LogOut,
  Folder,
  FolderOpen,
  ArrowLeft,
  ListFilter,
  ClipboardList,
} from "lucide-react";
import ExamManagement from "./ExamManagement";
/* ─────────────────────────────────────────────────────────
   Constants
   ────────────────────────────────────────────────────────── */

import { API_BASE_URL } from "../config";
const AUTO_REFRESH_INTERVAL_MS = 10000;

/* ─────────────────────────────────────────────────────────
   AuthedImage — Ảnh snapshot yêu cầu xác thực Token
   API /api/snapshots/{filename} nay bắt buộc có token giám thị, nhưng thẻ <img src="..."> tiêu
   chuẩn của trình duyệt KHÔNG gửi kèm được custom header. Component này tự fetch() ảnh có gắn
   header Authorization/X-Proctor-Token, rồi chuyển kết quả thành Object URL để hiển thị,
   thay vì nhúng token vào query string (tránh lộ token qua URL/lịch sử trình duyệt/log server).
   ────────────────────────────────────────────────────────── */
function AuthedImage({ url, token, alt, className, onClick }) {
  const [blobSrc, setBlobSrc] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!url) {
      setBlobSrc(null);
      return;
    }

    let cancelled = false;
    let objectUrl = null;
    setFailed(false);

    fetch(url, { headers: { "X-Proctor-Token": token } })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobSrc(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, token]);

  if (failed) {
    return (
      <div
        className={`${className} flex items-center justify-center bg-bg-card border border-border-default`}
      >
        <ImageIcon className="w-4 h-4 text-text-muted/40" />
      </div>
    );
  }

  if (!blobSrc) {
    return (
      <div
        className={`${className} bg-bg-card animate-pulse border border-border-default`}
      />
    );
  }

  return (
    <img
      src={blobSrc}
      alt={alt}
      className={className}
      onClick={onClick}
      loading="lazy"
    />
  );
}

const VIOLATION_TYPE_CONFIG = {
  NO_FACE: {
    label: "Vắng mặt",
    icon: EyeOff,
    color: "text-amber-700",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
  },
  TURNING_HEAD: {
    label: "Quay mặt",
    icon: Eye,
    color: "text-amber-700",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
  },
  PHONE_DETECTED: {
    label: "Điện thoại",
    icon: Smartphone,
    color: "text-red-700",
    bg: "bg-red-500/10",
    border: "border-red-500/30",
  },
  MULTIPLE_FACES: {
    label: "Nhiều người",
    icon: Users,
    color: "text-red-700",
    bg: "bg-red-500/10",
    border: "border-red-500/30",
  },
  CAMERA_BLOCKED: {
    label: "Camera bị che",
    icon: CameraOff,
    color: "text-red-700",
    bg: "bg-red-500/10",
    border: "border-red-500/30",
  },
  TAB_SWITCH: {
    label: "Chuyển tab",
    icon: MonitorCheck,
    color: "text-orange-700",
    bg: "bg-orange-500/10",
    border: "border-orange-500/30",
  },
  WINDOW_BLUR: {
    label: "Mất focus",
    icon: MonitorCheck,
    color: "text-orange-700",
    bg: "bg-orange-500/10",
    border: "border-orange-500/30",
  },
  FULLSCREEN_EXIT: {
    label: "Thoát fullscreen",
    icon: MonitorCheck,
    color: "text-orange-700",
    bg: "bg-orange-500/10",
    border: "border-orange-500/30",
  },
};

/* ──────────────────────────────────────────────────────────
   ProctorDashboard Component
   ────────────────────────────────────────────────────────── */

export default function ProctorDashboard({ teacherId, authToken, onLogout }) {
  // ── Tab điều hướng cấp cao nhất: 'giamsat' (Giám sát chống gian lận, mặc định) | 'dethi' (Quản lý đề thi) ──
  const [activeTab, setActiveTab] = useState("giamsat");

  // ── State ──
  const [violations, setViolations] = useState([]);
  const [students, setStudents] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedImage, setSelectedImage] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [confirmDeleteAll, setConfirmDeleteAll] = useState(false);
  const [deletingAll, setDeletingAll] = useState(false);

  // ── Điều hướng Giao diện: 'folders' = lưới thư mục theo sinh viên (mặc định) | 'detail' = bảng chi tiết ──
  const [viewMode, setViewMode] = useState("folders");
  const [studentSearch, setStudentSearch] = useState("");

  // ── Filters (áp dụng cho viewMode === 'detail') ──
  const [filterStudent, setFilterStudent] = useState("");
  const [filterType, setFilterType] = useState("");
  const [searchText, setSearchText] = useState("");

  const refreshTimerRef = useRef(null);
  const mountedRef = useRef(true);

  // Header xác thực Giám thị: gắn kèm vào MỌI request tới API bảo vệ bằng token
  const authHeaders = useMemo(
    () => ({ "X-Proctor-Token": authToken || "" }),
    [authToken],
  );

  // ──────────────────────────────────────────────────────
  // Fetch violations from API
  // ──────────────────────────────────────────────────────
  const fetchViolations = useCallback(
    async (showSpinner = false) => {
      if (showSpinner) setIsRefreshing(true);

      try {
        const params = new URLSearchParams();
        if (filterStudent) params.append("student_id", filterStudent);
        if (filterType) params.append("violation_type", filterType);
        params.append("limit", "500");

        const [violationsRes, statsRes] = await Promise.all([
          fetch(`${API_BASE_URL}/violations?${params.toString()}`, {
            headers: authHeaders,
          }),
          fetch(`${API_BASE_URL}/violations/stats`, { headers: authHeaders }),
        ]);

        if (violationsRes.status === 401 || statsRes.status === 401) {
          throw new Error(
            "Token xác thực không hợp lệ hoặc đã hết hạn — vui lòng đăng xuất và nhập lại token",
          );
        }
        if (!violationsRes.ok) throw new Error(`HTTP ${violationsRes.status}`);
        if (!statsRes.ok) throw new Error(`HTTP ${statsRes.status}`);

        const violationsData = await violationsRes.json();
        const statsData = await statsRes.json();

        if (mountedRef.current) {
          setViolations(violationsData);
          setStats(statsData);
          setError(null);
        }
      } catch (err) {
        console.error("Failed to fetch violations:", err);
        if (mountedRef.current) {
          setError(`Không thể kết nối Backend: ${err.message}`);
        }
      } finally {
        if (mountedRef.current) {
          setLoading(false);
          setIsRefreshing(false);
        }
      }
    },
    [filterStudent, filterType, authHeaders],
  );

  // ──────────────────────────────────────────────────────
  // Fetch danh sách "thư mục sinh viên" từ GET /api/students
  // Độc lập với bộ lọc của bảng chi tiết — luôn lấy TOÀN BỘ sinh viên để vẽ lưới thư mục.
  // ──────────────────────────────────────────────────────
  const fetchStudents = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/students`, {
        headers: authHeaders,
      });
      if (res.status === 401) {
        throw new Error(
          "Token xác thực không hợp lệ hoặc đã hết hạn — vui lòng đăng xuất và nhập lại token",
        );
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (mountedRef.current) setStudents(data);
    } catch (err) {
      console.error("Failed to fetch students:", err);
      if (mountedRef.current)
        setError(`Không thể kết nối Backend: ${err.message}`);
    }
  }, [authHeaders]);

  // ──────────────────────────────────────────────────────
  // Delete image (Manual Delete)
  // ──────────────────────────────────────────────────────
  const deleteViolationImage = useCallback(
    async (violationId) => {
      setDeletingId(violationId);

      try {
        const response = await fetch(
          `${API_BASE_URL}/violations/${violationId}/image`,
          {
            method: "DELETE",
            headers: authHeaders,
          },
        );

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `HTTP ${response.status}`);
        }

        // Update local state: set image_url = null
        if (mountedRef.current) {
          setViolations((prev) =>
            prev.map((v) =>
              v.id === violationId ? { ...v, image_url: null } : v,
            ),
          );
          setConfirmDeleteId(null);
        }
      } catch (err) {
        console.error("Failed to delete image:", err);
        if (mountedRef.current) {
          alert(`Lỗi xóa ảnh: ${err.message}`);
        }
      } finally {
        if (mountedRef.current) {
          setDeletingId(null);
        }
      }
    },
    [authHeaders],
  );

  // ──────────────────────────────────────────────────────
  // Delete ALL violations + images (Xóa toàn bộ vi phạm)
  // ──────────────────────────────────────────────────────
  const deleteAllViolations = useCallback(async () => {
    setDeletingAll(true);

    try {
      const response = await fetch(`${API_BASE_URL}/violations/all`, {
        method: "DELETE",
        headers: authHeaders,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP ${response.status}`);
      }

      const result = await response.json();

      if (mountedRef.current) {
        setViolations([]);
        setStats({
          total_violations: 0,
          total_with_images: 0,
          by_type: {},
          by_student: {},
        });
        setStudents([]);
        setConfirmDeleteAll(false);
        setViewMode("folders");
      }

      console.log("Deleted all violations successfully:", result);
    } catch (err) {
      console.error("Failed to delete all violations:", err);
      if (mountedRef.current) {
        alert(`Lỗi xóa tất cả: ${err.message}`);
      }
    } finally {
      if (mountedRef.current) {
        setDeletingAll(false);
      }
    }
  }, [authHeaders]);

  // ──────────────────────────────────────────────────────
  // Auto-refresh + Initial fetch
  // ──────────────────────────────────────────────────────
  useEffect(() => {
    mountedRef.current = true;
    fetchViolations(false);
    fetchStudents();

    refreshTimerRef.current = setInterval(() => {
      fetchViolations(false);
      fetchStudents();
    }, AUTO_REFRESH_INTERVAL_MS);

    return () => {
      mountedRef.current = false;
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
    };
  }, [fetchViolations, fetchStudents]);

  // ──────────────────────────────────────────────────────
  // Filtered violations (local text search)
  // ──────────────────────────────────────────────────────
  const filteredViolations = violations.filter((v) => {
    if (!searchText) return true;
    const lower = searchText.toLowerCase();
    return (
      v.student_id?.toLowerCase().includes(lower) ||
      (v.student_name || "").toLowerCase().includes(lower) ||
      v.violation_type?.toLowerCase().includes(lower) ||
      v.captured_at?.toLowerCase().includes(lower)
    );
  });

  // ──────────────────────────────────────────────────────
  // Format timestamp
  // ──────────────────────────────────────────────────────
  const formatDateTime = (isoString) => {
    if (!isoString) return "—";
    try {
      // SQLite timestamps from older API versions are UTC without an offset.
      const value = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(isoString)
        ? isoString : isoString + "Z";
      const d = new Date(value);
      return d.toLocaleString("vi-VN", {
        timeZone: "Asia/Ho_Chi_Minh",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return isoString;
    }
  };

  // Get unique student IDs for filter dropdown
  const uniqueStudents = [
    ...new Set(violations.map((v) => v.student_id)),
  ].sort();

  // ──────────────────────────────────────────────────────
  // Điều hướng Lưới Thư mục Sinh viên
  // ──────────────────────────────────────────────────────
  const openStudentFolder = (studentId) => {
    setFilterStudent(studentId);
    setSearchText("");
    setViewMode("detail");
  };

  const openAllViolations = () => {
    setFilterStudent("");
    setSearchText("");
    setViewMode("detail");
  };

  const backToFolders = () => {
    setViewMode("folders");
    setFilterStudent("");
  };

  // Danh sách sinh viên hiển thị trên lưới thư mục, có áp dụng ô tìm kiếm theo mã SV / họ tên
  const filteredStudents = students.filter((s) => {
    if (!studentSearch) return true;
    const q = studentSearch.toLowerCase();
    return (
      s.student_id?.toLowerCase().includes(q) ||
      (s.student_name || "").toLowerCase().includes(q)
    );
  });

  // Thông tin sinh viên đang được xem chi tiết (nếu có), dùng để hiển thị tiêu đề breadcrumb
  const currentStudentInfo = filterStudent
    ? students.find((s) => s.student_id === filterStudent)
    : null;

  // ────────────────────────────────────────────────────────────
  // RENDER
  // ────────────────────────────────────────────────────────────

  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Shield size={23} />
          </span>
          EduShield<span className="brand-ai">AI</span>
        </div>
        <p className="sidebar-label">KHÔNG GIAN GIẢNG VIÊN</p>
        <nav aria-label="Điều hướng giảng viên">
          <button
            aria-current={activeTab === "giamsat" ? "page" : undefined}
            className={activeTab === "giamsat" ? "active" : ""}
            onClick={() => setActiveTab("giamsat")}
          >
            <Shield size={19} />
            Giám sát thi
          </button>
          <button
            aria-current={activeTab === "dethi" ? "page" : undefined}
            className={activeTab === "dethi" ? "active" : ""}
            onClick={() => setActiveTab("dethi")}
          >
            <ClipboardList size={19} />
            Đề thi & kết quả
          </button>
        </nav>
        <div className="sidebar-guide">
          <Shield size={23} />
          <strong>Góc giám sát</strong>
          <p>
            Theo dõi dấu hiệu vi phạm và đối chiếu ảnh chứng cứ trước khi đánh
            giá.
          </p>
        </div>
        <div className="sidebar-account">
          <span className="account-avatar">GV</span>
          <div>
            <strong>{teacherId}</strong>
            <span>Giảng viên / Giám thị</span>
          </div>
          <button onClick={onLogout} aria-label="Đăng xuất" title="Đăng xuất">
            <LogOut size={18} />
          </button>
        </div>
      </aside>
      <header className="workspace-header">
        <div className="workspace-header-inner">
          <div className="breadcrumb">
            Không gian giảng viên <span>/</span>
            <strong>
              {activeTab === "giamsat" ? "Giám sát thi" : "Đề thi & kết quả"}
            </strong>
          </div>
          {/* Nav + Actions */}
          <div className="header-actions">
            <button
              onClick={onLogout}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-text-secondary border border-border-default hover:bg-bg-card-hover hover:text-text-primary transition-all cursor-pointer"
            >
              <LogOut className="w-4 h-4" />
              Thoát / Đổi mã
            </button>

            {activeTab === "giamsat" && (
              <>
                {/* ── Nút Xóa tất cả vi phạm ── */}
                {confirmDeleteAll ? (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={deleteAllViolations}
                      disabled={deletingAll}
                      className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold
                             bg-red-600 text-white hover:bg-red-500
                             disabled:opacity-50 transition-all cursor-pointer"
                    >
                      {deletingAll ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Đang xóa...
                        </>
                      ) : (
                        "Xác nhận xóa tất cả"
                      )}
                    </button>
                    <button
                      onClick={() => setConfirmDeleteAll(false)}
                      disabled={deletingAll}
                      className="px-3 py-2 rounded-xl text-sm font-medium bg-bg-card text-text-secondary
                             border border-border-default hover:bg-bg-card-hover transition-all cursor-pointer"
                    >
                      Hủy
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmDeleteAll(true)}
                    disabled={violations.length === 0}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold
                           bg-red-500/10 text-red-700 border border-red-500/30
                           hover:bg-red-500/20 transition-all cursor-pointer
                           disabled:opacity-30 disabled:cursor-not-allowed"
                    title="Xóa tất cả ảnh và dữ liệu vi phạm"
                  >
                    <Trash2 className="w-4 h-4" />
                    Xóa tất cả
                  </button>
                )}
                <button
                  onClick={() => {
                    fetchViolations(true);
                    fetchStudents();
                  }}
                  disabled={isRefreshing}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold
                         bg-accent-cyan/15 text-accent-cyan border border-cyan-500/30
                         hover:bg-accent-cyan/25 transition-all cursor-pointer disabled:opacity-50"
                >
                  <RefreshCw
                    className={`w-4 h-4 ${isRefreshing ? "animate-spin" : ""}`}
                  />
                  Làm mới
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* ═══ MAIN CONTENT ═══ */}
      <main id="main-content" className="workspace-main space-y-6">
        <section className="page-heading">
          <div>
            <p className="eyebrow">
              EDUSHIELD / {activeTab === "giamsat" ? "GIÁM SÁT" : "ĐỀ THI"}
            </p>
            <h1>
              {activeTab === "giamsat"
                ? "Tổng quan giám sát"
                : "Đề thi & kết quả"}
            </h1>
            <p>
              {activeTab === "giamsat"
                ? "Theo dõi vi phạm, tra cứu sinh viên và kiểm tra ảnh chứng cứ."
                : "Chuẩn bị đề thi, công bố và theo dõi kết quả tại đây."}
            </p>
          </div>
          {activeTab === "giamsat" && (
            <span className="refresh-indicator">
              <span className={error ? "status-error" : ""} />
              {error
                ? "Cần kiểm tra kết nối"
                : loading
                  ? "Đang kết nối…"
                  : "Tự cập nhật mỗi 10 giây"}
            </span>
          )}
        </section>
        {activeTab === "dethi" ? (
          <ExamManagement authToken={authToken} teacherId={teacherId} />
        ) : (
          <>
            {/* Error Banner */}
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-red-500/10 border border-red-500/30 rounded-2xl p-4 flex items-center gap-3"
              >
                <XCircle className="w-5 h-5 text-red-700 flex-shrink-0" />
                <p className="text-sm text-red-700">{error}</p>
                <button
                  onClick={() => {
                    fetchViolations(true);
                    fetchStudents();
                  }}
                  className="ml-auto text-sm text-red-700 underline hover:text-red-700 cursor-pointer"
                >
                  Thử lại
                </button>
              </motion.div>
            )}

            {/* ═══ STATS CARDS ═══ */}
            {stats && (
              <div className="stat-grid">
                {/* Total violations */}
                <div className="glass-card stat-card">
                  <div className="w-12 h-12 rounded-xl bg-red-500/10 flex items-center justify-center">
                    <AlertTriangle className="w-6 h-6 text-red-700" />
                  </div>
                  <div>
                    <p className="text-xs text-text-muted uppercase tracking-wide">
                      Tổng vi phạm
                    </p>
                    <p className="text-2xl font-bold text-text-primary">
                      {stats.total_violations}
                    </p>
                  </div>
                </div>

                {/* With images */}
                <div className="glass-card stat-card">
                  <div className="w-12 h-12 rounded-xl bg-cyan-500/10 flex items-center justify-center">
                    <ImageIcon className="w-6 h-6 text-cyan-700" />
                  </div>
                  <div>
                    <p className="text-xs text-text-muted uppercase tracking-wide">
                      Có ảnh chứng cứ
                    </p>
                    <p className="text-2xl font-bold text-text-primary">
                      {stats.total_with_images}
                    </p>
                  </div>
                </div>

                {/* Unique students */}
                <div className="glass-card stat-card">
                  <div className="w-12 h-12 rounded-xl bg-amber-500/10 flex items-center justify-center">
                    <Users className="w-6 h-6 text-amber-700" />
                  </div>
                  <div>
                    <p className="text-xs text-text-muted uppercase tracking-wide">
                      Sinh viên vi phạm
                    </p>
                    <p className="text-2xl font-bold text-text-primary">
                      {Object.keys(stats.by_student || {}).length}
                    </p>
                  </div>
                </div>

                {/* By type breakdown */}
                <div className="glass-card stat-card">
                  <div className="w-12 h-12 rounded-xl bg-purple-500/10 flex items-center justify-center">
                    <BarChart3 className="w-6 h-6 text-purple-700" />
                  </div>
                  <div>
                    <p className="text-xs text-text-muted uppercase tracking-wide">
                      Loại vi phạm
                    </p>
                    <p className="text-2xl font-bold text-text-primary">
                      {Object.keys(stats.by_type || {}).length}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* ═══ TYPE BREAKDOWN ═══ */}
            {stats?.by_type && Object.keys(stats.by_type).length > 0 && (
              <div className="glass-card violation-summary">
                <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4 flex items-center gap-2">
                  <BarChart3 className="w-4 h-4" /> Phân loại vi phạm
                </h3>
                <div className="flex flex-wrap gap-3">
                  {Object.entries(stats.by_type)
                    .sort((a, b) => b[1] - a[1])
                    .map(([type, count]) => {
                      const config = VIOLATION_TYPE_CONFIG[type] || {
                        label: type,
                        color: "text-slate-700",
                        bg: "bg-slate-500/10",
                        border: "border-slate-500/30",
                      };
                      return (
                        <div
                          key={type}
                          className={`${config.bg} ${config.border} border rounded-xl px-4 py-2.5 flex items-center gap-2`}
                        >
                          <span className={`text-sm font-bold ${config.color}`}>
                            {count}
                          </span>
                          <span className={`text-sm ${config.color}`}>
                            {config.label}
                          </span>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}

            {/* ═══ LƯỚI THƯ MỤC SINH VIÊN (VIEW MẶC ĐỊNH) ═══ */}
            {viewMode === "folders" && (
              <div className="space-y-5">
                {/* Thanh tìm kiếm sinh viên + lối tắt xem toàn bộ vi phạm dạng bảng phẳng */}
                <div className="glass-card overview-search flex flex-wrap items-center gap-3">
                  <div className="relative flex-1 min-w-[220px]">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
                    <input
                      type="text"
                      placeholder="Tìm theo mã sinh viên hoặc họ tên..."
                      value={studentSearch}
                      onChange={(e) => setStudentSearch(e.target.value)}
                      className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-bg-card border border-border-default 
                             text-text-primary text-sm placeholder-text-muted
                             focus:outline-none focus:border-accent-cyan/50 focus:ring-1 focus:ring-accent-cyan/30
                             transition-all"
                    />
                    {studentSearch && (
                      <button
                        onClick={() => setStudentSearch("")}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary cursor-pointer"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                  <button
                    onClick={openAllViolations}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold
                           bg-bg-card border border-border-default text-text-secondary
                           hover:bg-bg-card-hover hover:text-text-primary transition-all cursor-pointer whitespace-nowrap"
                  >
                    <ListFilter className="w-4 h-4" />
                    Xem tất cả vi phạm (bảng)
                  </button>
                </div>

                {/* Lưới thẻ thư mục — mỗi thẻ đại diện cho 1 sinh viên đã từng có vi phạm */}
                {loading ? (
                  <div className="glass-card flex items-center justify-center py-20">
                    <RefreshCw className="w-8 h-8 text-accent-cyan animate-spin" />
                    <span className="ml-3 text-text-secondary">
                      Đang tải dữ liệu...
                    </span>
                  </div>
                ) : filteredStudents.length === 0 ? (
                  <div className="glass-card flex flex-col items-center justify-center py-20 text-text-muted">
                    <CheckCircle2 className="w-16 h-16 mb-4 text-green-500/20" />
                    <p className="text-lg font-medium">
                      {students.length === 0
                        ? "Chưa có sinh viên nào vi phạm"
                        : "Không tìm thấy sinh viên phù hợp"}
                    </p>
                    <p className="text-sm mt-1">
                      Dữ liệu sẽ xuất hiện khi hệ thống ghi nhận vi phạm
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                    {filteredStudents.map((s, idx) => (
                      <motion.button
                        key={s.student_id}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: idx * 0.03 }}
                        onClick={() => openStudentFolder(s.student_id)}
                        className="glass-card student-folder p-5 text-left flex flex-col gap-3 hover:border-accent-cyan/40
                               hover:bg-bg-card-hover/40 transition-all cursor-pointer group"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div
                            className="w-11 h-11 rounded-xl bg-cyan-500/10 border border-cyan-500/20 
                                      flex items-center justify-center flex-shrink-0
                                      group-hover:bg-cyan-500/20 transition-colors"
                          >
                            <Folder className="w-5 h-5 text-accent-cyan" />
                          </div>
                          {s.violation_count > 0 && (
                            <span
                              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold 
                                         bg-red-500/10 text-red-700 border border-red-500/30 flex-shrink-0"
                            >
                              <AlertTriangle className="w-3 h-3" />
                              {s.violation_count}
                            </span>
                          )}
                        </div>

                        <div className="min-w-0">
                          <p className="text-base font-bold text-text-primary font-mono truncate">
                            {s.student_id}
                          </p>
                          <p className="text-sm text-text-secondary truncate mt-0.5">
                            {s.student_name || (
                              <span className="italic text-text-muted">
                                Chưa có tên
                              </span>
                            )}
                          </p>
                        </div>

                        <div className="flex items-center justify-between text-xs text-text-muted pt-2 border-t border-border-default">
                          <span className="flex items-center gap-1.5">
                            <ImageIcon className="w-3.5 h-3.5" />
                            {s.image_count} ảnh còn lưu
                          </span>
                          <span className="flex items-center gap-1.5">
                            <Clock className="w-3.5 h-3.5" />
                            {formatDateTime(s.latest_violation_at).split(
                              " ",
                            )[1] || "—"}
                          </span>
                        </div>
                      </motion.button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* ═══ CHI TIẾT VI PHẠM (BẢNG) — CỦA 1 SINH VIÊN HOẶC TOÀN BỘ ═══ */}
            {viewMode === "detail" && (
              <>
                {/* Breadcrumb quay lại lưới thư mục */}
                <div className="flex items-center gap-3">
                  <button
                    onClick={backToFolders}
                    className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-semibold
                       bg-bg-card border border-border-default text-text-secondary
                       hover:bg-bg-card-hover hover:text-text-primary transition-all cursor-pointer"
                  >
                    <ArrowLeft className="w-4 h-4" />
                    Danh sách sinh viên
                  </button>
                  <div className="flex items-center gap-2 text-text-secondary">
                    <FolderOpen className="w-4 h-4 text-accent-cyan flex-shrink-0" />
                    {filterStudent ? (
                      <span className="text-sm">
                        <span className="font-mono font-bold text-text-primary">
                          {filterStudent}
                        </span>
                        {currentStudentInfo?.student_name && (
                          <span className="text-text-muted">
                            {" "}
                            — {currentStudentInfo.student_name}
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="text-sm font-semibold text-text-primary">
                        Toàn bộ vi phạm
                      </span>
                    )}
                  </div>
                </div>

                {/* ═══ FILTERS ═══ */}
                <div className="glass-card p-5">
                  <div className="flex flex-wrap items-center gap-4">
                    {/* Search */}
                    <div className="relative flex-1 min-w-[200px]">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
                      <input
                        type="text"
                        placeholder="Tìm kiếm theo mã SV, loại vi phạm..."
                        value={searchText}
                        onChange={(e) => setSearchText(e.target.value)}
                        className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-bg-card border border-border-default 
                           text-text-primary text-sm placeholder-text-muted
                           focus:outline-none focus:border-accent-cyan/50 focus:ring-1 focus:ring-accent-cyan/30
                           transition-all"
                      />
                      {searchText && (
                        <button
                          onClick={() => setSearchText("")}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary cursor-pointer"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      )}
                    </div>

                    {/* Student filter — chỉ hiện khi đang ở chế độ "Toàn bộ vi phạm" (chưa chọn sẵn 1 SV từ lưới thư mục) */}
                    {!filterStudent && (
                      <div className="relative">
                        <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none" />
                        <select
                          value={filterStudent}
                          onChange={(e) => setFilterStudent(e.target.value)}
                          className="pl-10 pr-8 py-2.5 rounded-xl bg-bg-card border border-border-default
                             text-text-primary text-sm appearance-none cursor-pointer
                             focus:outline-none focus:border-accent-cyan/50 min-w-[160px]"
                        >
                          <option value="">Tất cả SV</option>
                          {uniqueStudents.map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                        <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none" />
                      </div>
                    )}

                    {/* Type filter */}
                    <div className="relative">
                      <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none" />
                      <select
                        value={filterType}
                        onChange={(e) => setFilterType(e.target.value)}
                        className="pl-10 pr-8 py-2.5 rounded-xl bg-bg-card border border-border-default
                           text-text-primary text-sm appearance-none cursor-pointer
                           focus:outline-none focus:border-accent-cyan/50 min-w-[180px]"
                      >
                        <option value="">Tất cả loại</option>
                        {Object.entries(VIOLATION_TYPE_CONFIG).map(
                          ([key, cfg]) => (
                            <option key={key} value={key}>
                              {cfg.label}
                            </option>
                          ),
                        )}
                      </select>
                      <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none" />
                    </div>

                    {/* Result count */}
                    <span className="text-sm text-text-muted">
                      {filteredViolations.length} kết quả
                    </span>
                  </div>
                </div>

                {/* ═══ VIOLATIONS TABLE ═══ */}
                <div className="glass-card overflow-hidden">
                  <div className="px-6 py-4 border-b border-border-default bg-bg-secondary/50 flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-2">
                      <Clock className="w-4 h-4" /> Nhật ký Vi phạm
                    </h2>
                    <span className="text-xs text-text-muted">
                      Tự động cập nhật mỗi 10 giây
                    </span>
                  </div>

                  {loading ? (
                    <div className="flex items-center justify-center py-20">
                      <RefreshCw className="w-8 h-8 text-accent-cyan animate-spin" />
                      <span className="ml-3 text-text-secondary">
                        Đang tải dữ liệu...
                      </span>
                    </div>
                  ) : filteredViolations.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-20 text-text-muted">
                      <CheckCircle2 className="w-16 h-16 mb-4 text-green-500/20" />
                      <p className="text-lg font-medium">Chưa có vi phạm nào</p>
                      <p className="text-sm mt-1">
                        Dữ liệu sẽ xuất hiện khi hệ thống ghi nhận vi phạm
                      </p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead>
                          <tr className="border-b border-border-default bg-bg-card/50">
                            <th className="px-5 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider">
                              ID
                            </th>
                            <th className="px-5 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider">
                              Ảnh chứng cứ
                            </th>
                            <th className="px-5 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider">
                              Mã SV
                            </th>
                            <th className="px-5 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider">
                              Loại vi phạm
                            </th>
                            <th className="px-5 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider">
                              Thời điểm
                            </th>
                            <th className="px-5 py-3 text-center text-xs font-semibold text-text-muted uppercase tracking-wider">
                              Hành động
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredViolations.map((v, idx) => {
                            const typeConfig = VIOLATION_TYPE_CONFIG[
                              v.violation_type
                            ] || {
                              label: v.violation_type,
                              color: "text-slate-700",
                              bg: "bg-slate-500/10",
                              border: "border-slate-500/30",
                            };
                            const TypeIcon = typeConfig.icon || AlertTriangle;

                            return (
                              <motion.tr
                                key={v.id}
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                transition={{ delay: idx * 0.02 }}
                                className="border-b border-border-default/50 hover:bg-bg-card-hover/50 transition-colors"
                              >
                                {/* ID */}
                                <td className="px-5 py-4">
                                  <span className="text-sm font-mono text-text-muted">
                                    #{v.id}
                                  </span>
                                </td>

                                {/* Thumbnail */}
                                <td className="px-5 py-4">
                                  {v.image_url ? (
                                    <button
                                      onClick={() =>
                                        setSelectedImage(v.image_url)
                                      }
                                      className="group relative cursor-pointer"
                                    >
                                      <AuthedImage
                                        url={v.image_url}
                                        token={authToken}
                                        alt={`Violation #${v.id}`}
                                        className="w-[80px] h-[60px] object-cover rounded-lg border border-border-default 
                                           group-hover:border-accent-cyan/50 transition-all shadow-sm"
                                      />
                                      <div
                                        className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 
                                              rounded-lg transition-opacity flex items-center justify-center"
                                      >
                                        <Eye className="w-4 h-4 text-white" />
                                      </div>
                                    </button>
                                  ) : (
                                    <div
                                      className="w-[80px] h-[60px] rounded-lg bg-bg-card border border-border-default 
                                            flex items-center justify-center"
                                    >
                                      <ImageIcon className="w-4 h-4 text-text-muted/30" />
                                    </div>
                                  )}
                                </td>

                                {/* Student ID + Họ tên */}
                                <td className="px-5 py-4">
                                  <div className="inline-flex flex-col bg-bg-card px-3 py-1.5 rounded-lg border border-border-default">
                                    <span className="text-sm font-semibold text-text-primary font-mono">
                                      {v.student_id}
                                    </span>
                                    {v.student_name && (
                                      <span className="text-xs text-text-muted truncate max-w-[160px]">
                                        {v.student_name}
                                      </span>
                                    )}
                                  </div>
                                </td>

                                {/* Type */}
                                <td className="px-5 py-4">
                                  <span
                                    className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold 
                                           ${typeConfig.bg} ${typeConfig.border} border`}
                                  >
                                    <TypeIcon
                                      className={`w-4 h-4 ${typeConfig.color}`}
                                    />
                                    <span className={typeConfig.color}>
                                      {typeConfig.label}
                                    </span>
                                  </span>
                                </td>

                                {/* Timestamp */}
                                <td className="px-5 py-4">
                                  <span className="text-sm text-text-secondary font-mono">
                                    {formatDateTime(v.captured_at)}
                                  </span>
                                </td>

                                {/* Actions */}
                                <td className="px-5 py-4 text-center">
                                  {v.image_url ? (
                                    confirmDeleteId === v.id ? (
                                      <div className="flex items-center justify-center gap-2">
                                        <button
                                          onClick={() =>
                                            deleteViolationImage(v.id)
                                          }
                                          disabled={deletingId === v.id}
                                          className="px-3 py-1.5 rounded-lg text-xs font-bold bg-red-600 text-white
                                             hover:bg-red-500 disabled:opacity-50 transition-all cursor-pointer"
                                        >
                                          {deletingId === v.id
                                            ? "Đang xóa..."
                                            : "Xác nhận"}
                                        </button>
                                        <button
                                          onClick={() =>
                                            setConfirmDeleteId(null)
                                          }
                                          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-bg-card text-text-secondary
                                             border border-border-default hover:bg-bg-card-hover transition-all cursor-pointer"
                                        >
                                          Hủy
                                        </button>
                                      </div>
                                    ) : (
                                      <button
                                        onClick={() => setConfirmDeleteId(v.id)}
                                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                                           bg-red-500/10 text-red-700 border border-red-500/30
                                           hover:bg-red-500/20 transition-all cursor-pointer"
                                        title="Xóa ảnh ngay (trước 24h)"
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                        Xóa ảnh
                                      </button>
                                    )
                                  ) : (
                                    <span className="text-xs text-text-muted italic">
                                      Đã xóa
                                    </span>
                                  )}
                                </td>
                              </motion.tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </>
            )}

            {/* Auto-cleanup note */}
            <div className="text-center py-4">
              <p className="text-xs text-text-muted">
                Ảnh chứng cứ được tự động xóa sau 24 giờ. Giám thị có thể xóa
                sớm hơn bằng nút "Xóa ảnh" ở mỗi hàng.
              </p>
            </div>
          </>
        )}
      </main>

      {/* ═══ IMAGE VIEWER MODAL ═══ */}
      <AnimatePresence>
        {selectedImage && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[9999] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6"
            onClick={() => setSelectedImage(null)}
          >
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.8, opacity: 0 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              className="relative max-w-3xl max-h-[80vh] w-full"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                onClick={() => setSelectedImage(null)}
                className="absolute -top-12 right-0 w-10 h-10 rounded-full bg-white/10 
                           hover:bg-white/20 flex items-center justify-center transition-all cursor-pointer"
              >
                <X className="w-5 h-5 text-white" />
              </button>
              <AuthedImage
                url={selectedImage}
                token={authToken}
                alt="Violation snapshot full view"
                className="w-full h-auto rounded-2xl shadow-2xl border border-white/10"
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
