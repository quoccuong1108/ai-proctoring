import { lazy, Suspense, useState } from "react";
import {
  Shield,
  GraduationCap,
  UserCog,
  ArrowRight,
  CheckCircle2,
  LockKeyhole,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { API_BASE_URL } from "./config";
const StudentExam = lazy(() => import("./components/StudentExam"));
const ProctorDashboard = lazy(() => import("./components/ProctorDashboard"));

export default function App() {
  const [role, setRole] = useState("student");
  const [savedTeacherSession] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem("teacher_session") || "null");
    } catch {
      sessionStorage.removeItem("teacher_session");
      return null;
    }
  });
  const [code, setCode] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem("exam_student_identity") || "{}").studentId || "";
    } catch {
      return "";
    }
  });
  const [fullName, setFullName] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem("exam_student_identity") || "{}").studentName || "";
    } catch {
      return "";
    }
  });
  const [teacherPassword, setTeacherPassword] = useState("");
  const [proctorToken, setProctorToken] = useState(
    () => savedTeacherSession?.access_token || "",
  );
  const [teacherInfo, setTeacherInfo] = useState(
    () => savedTeacherSession?.teacher || null,
  );
  const [activeRole, setActiveRole] = useState(() => {
    if (savedTeacherSession?.access_token && savedTeacherSession?.teacher) {
      return "proctor";
    }
    return sessionStorage.getItem("exam_student_identity") ? "student" : null;
  });
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const normalizedCode = code.trim().toUpperCase();


  const handleLogout = async () => {
    if (activeRole === "proctor" && proctorToken) {
      try {
        const logoutUrl = API_BASE_URL.endsWith("/api")
          ? `${API_BASE_URL}/auth/teacher/logout`
          : `${API_BASE_URL}/api/auth/teacher/logout`;
        await fetch(logoutUrl, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${proctorToken}`,
          },
        });
      } catch {
        // Tiếp tục đăng xuất cục bộ kể cả khi mạng lỗi
      }
    }
    sessionStorage.removeItem("exam_session_token");
    sessionStorage.removeItem("exam_request_token");
    sessionStorage.removeItem("exam_selected_info");
    sessionStorage.removeItem("exam_selected_choice");
    sessionStorage.removeItem("exam_selected_subject");
    sessionStorage.removeItem("exam_student_identity");
    sessionStorage.removeItem("exam_started");
    sessionStorage.removeItem("exam_progress");
    sessionStorage.removeItem("exam_result");
    sessionStorage.removeItem("teacher_session");
    sessionStorage.removeItem("teacher_dashboard_view");
    if (teacherInfo?.teacher_code) {
      sessionStorage.removeItem(
        `teacher_workspace_tab:${teacherInfo.teacher_code}`,
      );
    }
    sessionStorage.removeItem("teacher_enrollment_view");
    setActiveRole(null);
    setCode("");
    setFullName("");
    setProctorToken("");
    setTeacherPassword("");
    setTeacherInfo(null);
    setError("");
  };

  async function handleLogin(event) {
    event.preventDefault();
    setError("");

    const validCode =
      role === "student"
        ? normalizedCode.startsWith("SV")
        : /^GV-[A-Z0-9]{4}$/.test(normalizedCode);
    if (!validCode) {
      setError(
        role === "student"
          ? "Mã sinh viên phải bắt đầu bằng SV."
          : "Mã giảng viên phải đúng định dạng GV-xxxx, ví dụ GV-2026.",
      );
      return;
    }

    if (role === "student") {
      if (!fullName.trim()) {
        setError("Vui lòng nhập họ và tên.");
        return;
      }
      sessionStorage.setItem(
        "exam_student_identity",
        JSON.stringify({ studentId: normalizedCode, studentName: fullName.trim() }),
      );
      setActiveRole("student");
      return;
    }

    // Luồng đăng nhập Giảng viên qua API
    if (!teacherPassword) {
      setError("Vui lòng nhập mật khẩu tài khoản giảng viên.");
      return;
    }

    setIsLoading(true);
    try {
      const loginUrl = API_BASE_URL.endsWith("/api")
        ? `${API_BASE_URL}/auth/teacher/login`
        : `${API_BASE_URL}/api/auth/teacher/login`;

      const res = await fetch(loginUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          teacher_code: normalizedCode,
          password: teacherPassword,
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(
          data?.detail ||
            (res.status === 429
              ? "Quá nhiều lần đăng nhập sai. Vui lòng thử lại sau một phút."
              : "Mã giảng viên hoặc mật khẩu không chính xác."),
        );
      }

      const token = data.access_token;
      const teacher = data.teacher;
      if (typeof token !== "string" || !token || !teacher) {
        throw new Error("Máy chủ trả về thông tin đăng nhập không hợp lệ.");
      }

      setProctorToken(token);
      setTeacherInfo(teacher);
      sessionStorage.setItem(
        "teacher_session",
        JSON.stringify({ access_token: token, teacher }),
      );
      setTeacherPassword("");
      setActiveRole("proctor");
    } catch (err) {
      setError(err.message || "Không thể kết nối tới máy chủ.");
    } finally {
      setIsLoading(false);
    }
  }

  if (activeRole === "student")
    return (
      <Suspense fallback={<LoadingScreen />}>
        <StudentExam
          studentId={normalizedCode}
          studentName={fullName.trim()}
          onLogout={handleLogout}
        />
      </Suspense>
    );

  if (activeRole === "proctor")
    return (
      <Suspense fallback={<LoadingScreen />}>
        <ProctorDashboard
          teacherId={teacherInfo?.teacher_code || normalizedCode}
          teacherName={teacherInfo?.full_name || "Giảng viên"}
          authToken={proctorToken.trim()}
          onLogout={handleLogout}
        />
      </Suspense>
    );

  return (
    <main className="login-page">
      <section className="login-story">
        <a href="#" className="brand">
          <span className="brand-mark">
            <Shield size={25} />
          </span>
          EduShield<span className="brand-ai">AI</span>
        </a>
        <div className="story-content">
          <span className="eyebrow">KHÔNG GIAN THI TRỰC TUYẾN</span>
          <h1>
            Tập trung làm bài
            <br />
            <em>An tâm mỗi kỳ thi</em>
          </h1>
          <p>
            Một không gian kết nối sinh viên và giảng viên, từ chuẩn bị đề thi
            đến giám sát và đánh giá kết quả.
          </p>
          <div className="story-illustration" aria-hidden="true">
            <div className="illustration-top">
              <span className="illustration-dot" />
              <span>Không gian học thuật</span>
              <Shield size={18} />
            </div>
            <div className="illustration-body">
              <div className="illustration-icon">
                <GraduationCap size={38} />
              </div>
              <div>
                <strong>Sẵn sàng cho điều tiếp theo</strong>
                <span>Chuẩn bị · Làm bài · Hoàn thành</span>
              </div>
            </div>
            <div className="illustration-track">
              <i />
              <i />
              <i />
            </div>
            <div className="illustration-bottom">
              <CheckCircle2 size={16} /> Rõ ràng trong từng bước
            </div>
          </div>
          <div className="story-features">
            <span>
              <CheckCircle2 size={17} /> Giám sát bằng AI
            </span>
            <span>
              <CheckCircle2 size={17} /> Quản lý kỳ thi tập trung
            </span>
          </div>
        </div>
        <footer>
          EDUSHIELD AI <span>Học tập chủ động - Đánh giá minh bạch.</span>
        </footer>
      </section>
      <section className="login-form-area">
        <div className="login-form-wrap">
          <span className="eyebrow">CHÀO MỪNG BẠN TRỞ LẠI</span>
          <h2>Bắt đầu phiên làm việc</h2>
          <p className="login-subtitle">
            Chọn vai trò và nhập thông tin để tiếp tục.
          </p>
          <div className="role-picker" aria-label="Vai trò đăng nhập">
            {[
              ["student", "Sinh viên", GraduationCap],
              ["proctor", "Giảng viên", UserCog],
            ].map(([key, label, Icon]) => (
              <button
                key={key}
                type="button"
                aria-pressed={role === key}
                className={role === key ? "selected" : ""}
                onClick={() => {
                  setRole(key);
                  setCode("");
                  setTeacherPassword("");
                  setError("");
                }}
              >
                <Icon size={19} />
                {label}
              </button>
            ))}
          </div>
          <form onSubmit={handleLogin} className="login-form">
            <label htmlFor="identity">
              Mã {role === "student" ? "sinh viên" : "giảng viên"}
            </label>
            <input
              id="identity"
              autoComplete="username"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={role === "student" ? "VD: SV-2151220053" : "VD: GV-2026"}
              aria-invalid={!!error}
              aria-describedby={error ? "login-error" : undefined}
            />
            {role === "student" ? (
              <>
                <label htmlFor="full-name">Họ và tên</label>
                <input
                  id="full-name"
                  autoComplete="name"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Nhập đầy đủ họ và tên"
                />
              </>
            ) : (
              <>
                <label htmlFor="teacher-password">Mật khẩu</label>
                <input
                  id="teacher-password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={teacherPassword}
                  onChange={(e) => setTeacherPassword(e.target.value)}
                  placeholder="Nhập mật khẩu tài khoản giảng viên"
                />
              </>
            )}
            {error && (
              <p className="form-error" id="login-error" role="alert">
                <AlertCircle size={17} />
                {error}
              </p>
            )}
            <button
              className="primary-button login-submit"
              type="submit"
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <Loader2 size={18} className="animate-spin" />
                  Đang xác thực…
                </>
              ) : (
                <>
                  {role === "student" ? "Vào không gian thi" : "Đăng nhập quản lý"}
                  <ArrowRight size={18} />
                </>
              )}
            </button>
          </form>
          <p className="login-note">
            <LockKeyhole size={16} />
            {role === "student"
              ? "Bạn sẽ chọn môn và đề thi ở bước tiếp theo."
              : "Tài khoản giảng viên do quản trị viên cấp (dùng CLI create_teacher.py)."}
          </p>

        </div>
        <p className="login-help">
          EduShield AI · Hệ thống giám sát thi trực tuyến
        </p>
      </section>
    </main>
  );
}

function LoadingScreen() {
  return (
    <div className="route-loading" role="status">
      <Shield size={32} />
      <p>Đang mở không gian làm việc…</p>
    </div>
  );
}
