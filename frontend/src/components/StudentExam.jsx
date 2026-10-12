import StudentGateway from "./StudentGateway";
/**
 * EduShield AI — Component Phòng thi Sinh viên (StudentExam)
 *
 * Kiến trúc Giám sát Trực tuyến Phía Client (Client-side AI Proctoring):
 * 1. Thu nhận luồng hình ảnh: Sử dụng WebRTC navigator.mediaDevices.getUserMedia để kết nối Camera thời gian thực.
 * 2. Phân tích AI cục bộ trên trình duyệt (Edge Computing bằng MediaPipe Tasks-Vision WebAssembly):
 *    - FaceLandmarker: Phát hiện khuôn mặt (Face Detection) và 468 điểm mốc (Face Mesh landmarks) để ước tính hướng quay mặt (Head Pose Estimation).
 *    - ObjectDetector: Phát hiện thiết bị gian lận (đặc biệt là điện thoại di động "cell phone" theo chuẩn tập dữ liệu COCO).
 *    - Pixel-level Brightness Check: Kiểm tra độ sáng trung bình qua HTML5 Canvas để phát hiện hành vi che camera / phòng tối.
 * 3. Event-driven: Chỉ khi phát hiện trạng thái vi phạm mới trích xuất ảnh Snapshot Base64 qua Canvas và gửi HTTP POST lên Backend FastAPI để lưu trữ bằng chứng.
 * 4. Chống gian lận trình duyệt (Browser Lockdown): Bắt buộc chế độ Fullscreen, chống chuyển Tab (Visibility API), chống gian lận bàn phím / chuột.
 *
 * Danh mục vi phạm được giám sát:
 *   - NO_FACE: Không tìm thấy khuôn mặt thí sinh trong khung hình
 *   - TURNING_HEAD: Thí sinh ngoảnh mặt sang trái/phải quá lâu (> 3.6 giây)
 *   - MULTIPLE_FACES: Phát hiện từ 2 khuôn mặt trở lên trong khung hình
 *   - PHONE_DETECTED: Phát hiện điện thoại di động
 *   - CAMERA_BLOCKED: Camera bị che mờ hoặc phòng thi không đủ ánh sáng
 *   - LOCKDOWN: Thoát Fullscreen hoặc chuyển Tab trình duyệt
 */

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Shield,
  Clock,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
  Eye,
  EyeOff,
  Smartphone,
  Users,
  Camera,
  CameraOff,
  Maximize,
  Monitor,
  ScrollText,
  CircleDot,
  Send,
  Loader2,
  Cpu,
  LogOut,
  Trophy,
  XCircle,
  FileQuestion,
  Hourglass,
  ArrowLeft,
  RefreshCw,
} from "lucide-react";
import {
  FaceLandmarker,
  FilesetResolver,
  ObjectDetector,
} from "@mediapipe/tasks-vision";
import useBrowserLockdown from "../hooks/useBrowserLockdown";

/* ──────────────────────────────────────────────────────────
   CÁC HẰNG SỐ CẤU HÌNH HỆ THỐNG (CONSTANTS)
   ────────────────────────────────────────────────────────── */

import { API_BASE_URL, IS_MOBILE_DEVICE } from "../config";

// Chu kỳ phân tích AI: 300ms (~3.3 FPS) trên máy tính; 500ms (2 FPS) trên điện thoại để đỡ nóng máy/hao pin.
const DETECTION_INTERVAL_MS = IS_MOBILE_DEVICE ? 500 : 300;

// Số frame liên tiếp quay mặt để xác nhận vi phạm — quy đổi để luôn ≈ 3.6 giây bất kể chu kỳ
// (300ms → 12 frame như trước; 500ms → 8 frame).
const TURNING_HEAD_FRAME_THRESHOLD = Math.ceil(3600 / DETECTION_INTERVAL_MS);

// Các vi phạm lockdown (khác vi phạm do AI camera) được gửi lên server để giảng viên xem trong log.
// Đều nằm trong VALID_VIOLATION_TYPES của backend; các loại còn lại (phím tắt, chuột phải...) chỉ hiện cục bộ.
const LOCKDOWN_TYPES_SENT_TO_SERVER = new Set([
  "TAB_SWITCH",
  "WINDOW_BLUR",
  "FULLSCREEN_EXIT",
]);

// Khoảng thời gian giãn cách (cooldown) giữa 2 lần gửi cùng 1 loại vi phạm lên server: 5000ms (5 giây)
const VIOLATION_COOLDOWN_MS = 5000;

// Ngưỡng tính toán góc xoay đầu (Head Pose Estimation):
// Tỷ lệ độ lệch mũi so với tâm 2 mắt (vùng an toàn nới rộng: 0.25 - 0.75 để thí sinh thoải mái đọc đề)
const HEAD_TURN_NOSE_OFFSET_RATIO = 0.25;

// Tỷ lệ bất đối xứng khoảng cách từ mũi đến 2 mắt (trái vs phải)
const HEAD_TURN_EYE_ASYMMETRY = 1.25;

// Bản đồ cấu hình giao diện cho từng loại trạng thái giám sát AI
const STATUS_CONFIG = {
  NORMAL: {
    label: "Hợp lệ",
    description: "Trạng thái bình thường, tập trung làm bài",
    color: "text-green-700",
    bgColor: "bg-green-500/10",
    borderColor: "border-green-500/30",
    icon: CheckCircle2,
  },
  NO_FACE: {
    label: "Vắng mặt",
    description: "Không phát hiện thí sinh trước camera",
    color: "text-amber-700",
    bgColor: "bg-amber-500/10",
    borderColor: "border-amber-500/30",
    icon: EyeOff,
  },
  TURNING_HEAD: {
    label: "Quay mặt",
    description: "Thí sinh ngoảnh mặt khỏi màn hình quá lâu",
    color: "text-amber-700",
    bgColor: "bg-amber-500/10",
    borderColor: "border-amber-500/30",
    icon: Eye,
  },
  MULTIPLE_FACES: {
    label: "Nhiều người",
    description: "Phát hiện nhiều hơn 1 khuôn mặt trong phòng thi",
    color: "text-red-700",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/30",
    icon: Users,
  },
  PHONE_DETECTED: {
    label: "Điện thoại",
    description: "Phát hiện thiết bị điện thoại di động",
    color: "text-red-700",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/30",
    icon: Smartphone,
  },
  CAMERA_BLOCKED: {
    label: "Camera bị che",
    description: "Phát hiện camera bị che mờ hoặc không đủ sáng",
    color: "text-red-700",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/30",
    icon: CameraOff,
  },
  INITIALIZING: {
    label: "Đang khởi tạo AI",
    description: "Đang chuẩn bị giám sát, vui lòng chờ…",
    color: "text-slate-700",
    bgColor: "bg-slate-500/10",
    borderColor: "border-slate-500/30",
    icon: Loader2,
  },
};

/* ──────────────────────────────────────────────────────────
   COMPONENT CHÍNH: StudentExam
   ────────────────────────────────────────────────────────── */

export default function StudentExam({ studentId, studentName, onLogout }) {
  // Trạng thái bắt đầu làm bài thi (mặc định là true khi đăng nhập từ App.jsx)

  // Trạng thái AI hiện tại hiển thị trên giao diện (NORMAL, TURNING_HEAD, PHONE_DETECTED, ...)
  const [aiStatus, setAiStatus] = useState("INITIALIZING");

  // Trạng thái báo hiệu mô hình AI và camera đã nạp hoàn tất sẵn sàng chạy
  const [aiReady, setAiReady] = useState(false);
  const [aiInitError, setAiInitError] = useState("");

  // ── Trạng thái luồng chọn đề và phiên thi ──
  const [isExamStarted, setIsExamStarted] = useState(false);
  const [examData, setExamData] = useState(null); // { exam_id, exam_code, title, duration_minutes, questions }
  const [examLoading, setExamLoading] = useState(false);
  const [examLoadError, setExamLoadError] = useState("");

  // Giai đoạn C: Đề thi theo môn & Phê duyệt thí sinh
  const [availableData, setAvailableData] = useState([]);
  const [loadingAvailable, setLoadingAvailable] = useState(false);
  const [availableError, setAvailableError] = useState("");
  const [selectedSubject, setSelectedSubject] = useState(
    () => sessionStorage.getItem("exam_selected_subject") || "",
  );
  const [selectedExamChoice, setSelectedExamChoice] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem("exam_selected_choice") || "null");
    } catch {
      sessionStorage.removeItem("exam_selected_choice");
      return null;
    }
  });
  const [selectedExamInfo, setSelectedExamInfo] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem("exam_selected_info") || "null");
    } catch {
      return null;
    }
  });
  const [enrollmentState, setEnrollmentState] = useState(() => {
    if (sessionStorage.getItem("exam_session_token")) return "APPROVED";
    if (sessionStorage.getItem("exam_request_token")) return "PENDING";
    return null;
  }); // 'PENDING' | 'APPROVED' | 'REJECTED' | 'REVOKED'
  const [rejectReason, setRejectReason] = useState("");
  const [requestToken, setRequestToken] = useState(() => {
    return sessionStorage.getItem("exam_request_token") || "";
  });
  const [cancelingJoinRequest, setCancelingJoinRequest] = useState(false);
  useEffect(() => {
    if (selectedExamInfo) {
      sessionStorage.setItem("exam_selected_info", JSON.stringify(selectedExamInfo));
    } else {
      sessionStorage.removeItem("exam_selected_info");
    }
  }, [selectedExamInfo]);
  useEffect(() => {
    if (selectedSubject) {
      sessionStorage.setItem("exam_selected_subject", selectedSubject);
    } else {
      sessionStorage.removeItem("exam_selected_subject");
    }
    if (selectedExamChoice) {
      sessionStorage.setItem("exam_selected_choice", JSON.stringify(selectedExamChoice));
    } else {
      sessionStorage.removeItem("exam_selected_choice");
    }
  }, [selectedSubject, selectedExamChoice]);
  useEffect(() => {
    if (requestToken) {
      sessionStorage.setItem("exam_request_token", requestToken);
    } else {
      sessionStorage.removeItem("exam_request_token");
    }
  }, [requestToken]);
  const [examSessionToken, setExamSessionToken] = useState(() => {
    return sessionStorage.getItem("exam_session_token") || "";
  });
  const examSessionTokenRef = useRef(examSessionToken);
  useEffect(() => {
    examSessionTokenRef.current = examSessionToken;
    if (examSessionToken) {
      sessionStorage.setItem("exam_session_token", examSessionToken);
    } else {
      sessionStorage.removeItem("exam_session_token");
    }
  }, [examSessionToken]);


  // Trạng thái bấm "Bắt đầu làm bài": gọi server ghi giờ bắt đầu rồi mới chạy đồng hồ/camera
  const [startingExam, setStartingExam] = useState(false);
  const [startError, setStartError] = useState("");

  // ── Trạng thái nộp bài & kết quả chấm điểm tự động trả về từ backend ──
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [examResult, setExamResult] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem("exam_result") || "null");
    } catch {
      sessionStorage.removeItem("exam_result");
      return null;
    }
  }); // { total_score, correct_count, total_questions, pass_score, passed }
  const hasAutoSubmittedRef = useRef(false); // chặn gọi nộp bài 2 lần khi hết giờ (StrictMode double-invoke)

  // Vị trí câu hỏi hiện tại đang hiển thị (0-indexed)
  const [currentQuestion, setCurrentQuestion] = useState(0);

  // Bảng lưu trữ đáp án thí sinh đã chọn: { [question.id]: 'A'|'B'|'C'|'D' } — dùng thẳng
  // question.id và chữ cái đáp án để khớp 1-1 với payload API POST .../submit, không cần
  // ánh xạ ngược từ index sang id/letter khi nộp bài.
  const [answers, setAnswers] = useState({});

  // Thời gian còn lại của bài thi tính bằng giây — khởi tạo 0, được set lại đúng giá trị
  // thật (examData.duration_minutes * 60) ngay khi tải đề thành công (xem hàm loadExam).
  const [timeLeft, setTimeLeft] = useState(0);

  // ── Các tham chiếu (Refs) quản lý DOM, luồng dữ liệu ngầm và chu kỳ AI ──
  const videoRef = useRef(null); // Thẻ <video> ngầm dùng để cấp khung hình cho MediaPipe xử lý
  const canvasRef = useRef(null); // Thẻ <canvas> ngầm dùng để trích xuất ảnh vi phạm Base64
  const liveVideoRef = useRef(null); // Thẻ <video> hiển thị khung hình camera trực tiếp cho thí sinh quan sát
  const streamRef = useRef(null); // Lưu trữ MediaStream của Camera thiết bị để giải phóng khi unmount
  const detectionIntervalRef = useRef(null); // Timer lặp lại chu kỳ phân tích AI (300ms)
  const faceLandmarkerRef = useRef(null); // Thể hiện (instance) của mô hình MediaPipe FaceLandmarker
  const objectDetectorRef = useRef(null); // Thể hiện (instance) của mô hình MediaPipe ObjectDetector
  const lastViolationTimeRef = useRef({}); // Bộ đếm thời gian cooldown tránh gửi trùng lặp vi phạm liên tục
  const turningHeadFramesRef = useRef(0); // Bộ đếm số frame liên tiếp thí sinh quay mặt (giảm false positive)
  const mountedRef = useRef(true); // Cờ kiểm soát vòng đời component, ngăn memory leak khi unmount

  // Danh sách lịch sử các sự kiện vi phạm được ghi nhận trong phiên thi của thí sinh
  const [violationLogs, setViolationLogs] = useState([]);

  // Tích hợp hook chống gian lận cấp trình duyệt (useBrowserLockdown)
  // onViolation trỏ tới lockdownReportRef — gắn sau khi sendViolation được khai báo (xem effect bên dưới)
  const lockdownReportRef = useRef(null);
  const examActiveRef = useRef(false); // chỉ báo vi phạm lockdown lên server khi đang thật sự làm bài
  const {
    isFullscreen,
    showFullscreenOverlay,
    showBlurOverlay,
    tabSwitchCount,
    violations: lockdownViolations,
    requestFullscreen,
    dismissBlurOverlay,
  } = useBrowserLockdown({
    onViolation: (type) => lockdownReportRef.current?.(type),
  });

  // Biến cờ xác định trạng thái hiện tại có đang bị vi phạm hay không (đổi viền đỏ cho camera)
  const isViolation = aiStatus !== "NORMAL" && aiStatus !== "INITIALIZING";

  // Lấy thông tin nhãn, màu sắc và biểu tượng tương ứng với trạng thái AI hiện tại
  const currentStatusConfig =
    STATUS_CONFIG[aiStatus] || STATUS_CONFIG.INITIALIZING;

  // Tính toán tiến độ làm bài (an toàn khi examData chưa tải xong: mặc định 0 câu)
  const totalQuestions = examData?.questions?.length || 0;
  const answeredCount = Object.keys(answers).length;
  const progressPercent =
    totalQuestions > 0 ? (answeredCount / totalQuestions) * 100 : 0;

  /**
   * Chức năng: Chụp ảnh bằng chứng vi phạm (Snapshot) qua HTML5 Canvas
   * Trả về chuỗi Base64 định dạng JPEG chất lượng 0.6 để tối ưu băng thông mạng truyền tải
   */
  const captureSnapshot = useCallback(() => {
    try {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas || video.readyState < 2) return null;

      const ctx = canvas.getContext("2d");
      // Giữ đúng tỷ lệ khung hình của camera (điện thoại thường quay dọc 3:4, không phải 4:3)
      const snapWidth = 320;
      const snapHeight = Math.round(
        (snapWidth * (video.videoHeight || 3)) / (video.videoWidth || 4),
      );
      canvas.width = snapWidth;
      canvas.height = snapHeight;
      ctx.drawImage(video, 0, 0, snapWidth, snapHeight);
      return canvas.toDataURL("image/jpeg", 0.6);
    } catch (err) {
      console.error("Lỗi khi chụp snapshot camera:", err);
      return null;
    }
  }, []);

  /**
   * Chức năng: Gửi bản tin ghi nhận vi phạm lên Backend FastAPI (HTTP POST /api/violations)
   * Có cơ chế Cooldown 5s cho cùng 1 loại vi phạm để chống spam mạng
   */
  const sendViolation = useCallback(
    async (violationType, snapshotBase64) => {
      const activeToken = examSessionTokenRef.current;
      if (!studentId || !activeToken) return;

      // Kiểm tra thời gian giãn cách (cooldown) giữa 2 lần gửi cùng loại vi phạm
      const now = Date.now();
      const lastTime = lastViolationTimeRef.current[violationType] || 0;
      if (now - lastTime < VIOLATION_COOLDOWN_MS) return;
      lastViolationTimeRef.current[violationType] = now;

      // Gói tin chuẩn hóa gửi lên API
      const payload = {
        violation_type: violationType,
        captured_at: new Date().toISOString(),
        image_base64: snapshotBase64 || null,
      };

      // Cập nhật ngay vào danh sách log phía giao diện (Optimistic UI Update)
      const statusInfo = STATUS_CONFIG[violationType];
      if (statusInfo) {
        const logEntry = {
          id: now,
          time: new Date(payload.captured_at).toLocaleTimeString("vi-VN", {
            timeZone: "Asia/Ho_Chi_Minh",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }),
          type: violationType,
          label: statusInfo.label,
          message: statusInfo.description,
          image: snapshotBase64,
        };
        setViolationLogs((prev) => [logEntry, ...prev].slice(0, 100));
      }

      // Gửi yêu cầu bất đồng bộ đến máy chủ giám sát
      try {
        const headers = { "Content-Type": "application/json" };
        headers["X-Exam-Session"] = activeToken;
        const response = await fetch(`${API_BASE_URL}/violations`, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          console.warn(
            "Máy chủ từ chối bản tin vi phạm:",
            response.status,
            errorData,
          );
        }
      } catch (err) {
        console.error("Lỗi kết nối khi gửi bản tin vi phạm tới backend:", err);
      }
    },
    [studentId],
  );

  // Gắn hàm báo vi phạm lockdown (chuyển tab / mất focus / thoát fullscreen) lên server.
  // Trước đây 3 loại này chỉ hiện ở màn hình sinh viên, giảng viên không thấy trong log.
  useEffect(() => {
    lockdownReportRef.current = (type) => {
      if (!examActiveRef.current || !LOCKDOWN_TYPES_SENT_TO_SERVER.has(type)) return;
      sendViolation(type, captureSnapshot());
    };
  }, [sendViolation, captureSnapshot]);

  /**
   * Chức năng: Phân tích hướng quay mặt (Head Pose Estimation) dựa trên toạ độ các điểm mốc khuôn mặt (Face Landmarks)
   * Thuật toán:
   * - Xác định toạ độ chóp mũi (Mốc 1) và khoé mắt trong của 2 mắt (Mốc 133 và Mốc 362)
   * - Tính tâm mắt và khoảng cách 2 mắt
   * - Tính tỷ lệ lệch mũi so với tâm mắt: Nếu vượt quá HEAD_TURN_NOSE_OFFSET_RATIO (0.25) -> Quay mặt
   * - Tính tỷ lệ bất đối xứng mắt-mũi: Nếu vượt quá HEAD_TURN_EYE_ASYMMETRY (1.25) -> Quay mặt
   */
  const analyzeHeadPose = useCallback((landmarks) => {
    try {
      const noseTip = landmarks[1]; // Mốc toạ độ chóp mũi
      const leftEyeInner = landmarks[133]; // Mốc toạ độ khoé mắt trái
      const rightEyeInner = landmarks[362]; // Mốc toạ độ khoé mắt phải

      if (!noseTip || !leftEyeInner || !rightEyeInner) return false;

      // 1. Tính tâm toạ độ giữa 2 mắt
      const eyeCenterX = (leftEyeInner.x + rightEyeInner.x) / 2;
      const eyeDistance = Math.abs(rightEyeInner.x - leftEyeInner.x);

      // 2. Độ lệch tâm của chóp mũi so với trục giữa của mắt
      const noseOffset = Math.abs(noseTip.x - eyeCenterX);
      const noseOffsetRatio = noseOffset / (eyeDistance + 1e-6);

      if (noseOffsetRatio > HEAD_TURN_NOSE_OFFSET_RATIO) {
        return true;
      }

      // 3. Tỷ lệ bất đối xứng khoảng cách từ mũi sang mắt trái và mắt phải
      const distLeft = Math.abs(noseTip.x - leftEyeInner.x);
      const distRight = Math.abs(noseTip.x - rightEyeInner.x);
      const asymmetryRatio =
        Math.max(distLeft, distRight) / (Math.min(distLeft, distRight) + 1e-6);

      if (asymmetryRatio > HEAD_TURN_EYE_ASYMMETRY) {
        return true;
      }

      return false;
    } catch (err) {
      console.error("Lỗi phân tích góc nghiêng đầu:", err);
      return false;
    }
  }, []);

  /**
   * Chức năng: Vòng lặp phân tích AI cốt lõi (Core Detection Loop)
   * Thực hiện mỗi 300ms (~3.3 FPS):
   *   Bước 0: Kiểm tra Camera có bị che / phòng tối qua độ sáng trung bình của Canvas
   *   Bước 1: Phân tích FaceLandmarker (số lượng khuôn mặt, toạ độ mốc)
   *   Bước 2: Phân tích ObjectDetector (quét đối tượng điện thoại 'cell phone')
   *   Bước 3: Tổng hợp trạng thái theo độ ưu tiên: Che cam > Điện thoại > Nhiều người > Vắng mặt > Quay mặt > Bình thường
   *   Bước 4: Cập nhật giao diện và gửi vi phạm (nếu có)
   */
  const runDetection = useCallback(() => {
    const video = videoRef.current;
    const faceLandmarker = faceLandmarkerRef.current;
    const objectDetector = objectDetectorRef.current;

    if (!video || !faceLandmarker || video.readyState < 2) return;

    try {
      const timestamp = performance.now();

      // ═══ BƯỚC 0: Kiểm tra camera bị che / phòng quá tối ═══
      let isCameraBlocked = false;
      const canvas = canvasRef.current;
      if (canvas && video.videoWidth > 0) {
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        canvas.width = 64;
        canvas.height = 48;
        ctx.drawImage(video, 0, 0, 64, 48);
        const imageData = ctx.getImageData(0, 0, 64, 48).data;
        let sumBrightness = 0;
        let count = 0;
        // Lấy mẫu nhanh từng pixel (bước nhảy 16 bytes = 4 pixel)
        for (let i = 0; i < imageData.length; i += 16) {
          sumBrightness +=
            0.299 * imageData[i] +
            0.587 * imageData[i + 1] +
            0.114 * imageData[i + 2];
          count++;
        }
        const avgBrightness = sumBrightness / count;
        if (avgBrightness < 15) {
          // Ngưỡng đen / bị che
          isCameraBlocked = true;
        }
      }

      // ═══ BƯỚC 1: Nhận diện khuôn mặt & Trích xuất điểm mốc ═══
      const faceResults = faceLandmarker.detectForVideo(video, timestamp);
      const faceCount = faceResults.faceLandmarks?.length || 0;

      // ═══ BƯỚC 2: Nhận diện thiết bị điện thoại qua MediaPipe ObjectDetector ═══
      let phoneDetected = false;
      if (objectDetector) {
        try {
          const objResults = objectDetector.detectForVideo(video, timestamp);
          for (const detection of objResults.detections || []) {
            for (const category of detection.categories || []) {
              if (
                category.categoryName === "cell phone" &&
                category.score > 0.25
              ) {
                phoneDetected = true;
                break;
              }
            }
            if (phoneDetected) break;
          }
        } catch (objErr) {
          console.debug("Lỗi frame quét đối tượng:", objErr);
        }
      }

      // ═══ BƯỚC 3: Xác định trạng thái theo thứ tự ưu tiên ═══
      let newStatus = "NORMAL";
      let isCurrentlyTurning = false;

      if (isCameraBlocked) {
        newStatus = "CAMERA_BLOCKED";
      } else if (phoneDetected) {
        newStatus = "PHONE_DETECTED";
      } else if (faceCount > 1) {
        newStatus = "MULTIPLE_FACES";
      } else if (faceCount === 0) {
        newStatus = "NO_FACE";
      } else if (faceCount === 1 && faceResults.faceLandmarks[0]) {
        // Kiểm tra góc xoay đầu
        const isTurning = analyzeHeadPose(faceResults.faceLandmarks[0]);
        if (isTurning) {
          isCurrentlyTurning = true;
          turningHeadFramesRef.current += 1;
          // Ngưỡng: ≈ 3.6 giây quay mặt liên tục (TURNING_HEAD_FRAME_THRESHOLD frame) mới xác nhận vi phạm
          if (turningHeadFramesRef.current >= TURNING_HEAD_FRAME_THRESHOLD) {
            newStatus = "TURNING_HEAD";
          }
        }
      }

      // Nếu thí sinh nhìn thẳng lại màn hình, đặt lại bộ đếm frame quay mặt
      if (!isCurrentlyTurning) {
        turningHeadFramesRef.current = 0;
      }

      // ═══ BƯỚC 4: Cập nhật UI & Gửi sự kiện vi phạm ═══
      if (mountedRef.current) {
        // Chỉ cập nhật state khi trạng thái thực sự thay đổi để tránh re-render thừa
        setAiStatus((prev) => (prev !== newStatus ? newStatus : prev));
      }

      // Nếu có vi phạm khác NORMAL, chụp ảnh snapshot và gửi lên server
      if (newStatus !== "NORMAL") {
        const snapshot = captureSnapshot();
        sendViolation(newStatus, snapshot);
      }
    } catch (err) {
      console.error("Lỗi trong vòng lặp AI:", err);
    }
  }, [analyzeHeadPose, captureSnapshot, sendViolation]);

  /**
   * Khởi tạo các mô hình MediaPipe AI và luồng Camera người dùng
   * Chạy một lần khi thí sinh vào phòng thi
   */
  useEffect(() => {
    if (!isExamStarted) return;

    mountedRef.current = true;
    let cancelled = false;

    async function initAI() {
      try {
        // 1. Tải môi trường thực thi WebAssembly (WASM) của MediaPipe
        const vision = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm",
        );

        if (cancelled) return;

        // 2. Tạo mô hình FaceLandmarker — ưu tiên GPU, tự lùi về CPU nếu thiết bị/trình duyệt
        //    (đặc biệt một số điện thoại, iOS Safari) không khởi tạo được GPU delegate
        const faceLandmarkerOptions = (delegate) => ({
          baseOptions: {
            modelAssetPath:
              "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
            delegate,
          },
          runningMode: "VIDEO",
          numFaces: 3,
          minFaceDetectionConfidence: 0.5,
          minTrackingConfidence: 0.5,
        });
        let faceLandmarker;
        try {
          faceLandmarker = await FaceLandmarker.createFromOptions(
            vision,
            faceLandmarkerOptions("GPU"),
          );
        } catch (gpuErr) {
          console.warn("GPU delegate không dùng được, chuyển sang CPU:", gpuErr);
          faceLandmarker = await FaceLandmarker.createFromOptions(
            vision,
            faceLandmarkerOptions("CPU"),
          );
        }
        faceLandmarkerRef.current = faceLandmarker;

        if (cancelled) return;

        // 3. Tạo mô hình ObjectDetector nhận diện điện thoại
        try {
          const objectDetector = await ObjectDetector.createFromOptions(
            vision,
            {
              baseOptions: {
                modelAssetPath:
                  "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite",
                delegate: "CPU",
              },
              runningMode: "VIDEO",
              maxResults: 5,
              scoreThreshold: 0.25,
            },
          );
          objectDetectorRef.current = objectDetector;
        } catch (objErr) {
          console.warn(
            "Không thể tải ObjectDetector (tính năng phát hiện điện thoại tạm tắt):",
            objErr,
          );
        }

        if (cancelled) return;

        // 4. Kết nối camera thiết bị của thí sinh thông qua WebRTC (ideal: không ép cứng độ phân giải
        //    để điện thoại tự chọn khung hình dọc/ngang phù hợp)
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 640 },
            height: { ideal: 480 },
            facingMode: "user",
          },
        });

        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }

        streamRef.current = stream;

        // Gán luồng camera vào video phân tích ngầm. Gọi play() tường minh vì iOS Safari
        // không phải lúc nào cũng tự phát dù đã có autoPlay + muted + playsInline.
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play?.().catch(() => {});
          // Có giới hạn 8 giây: nếu trình duyệt không bắn onloadeddata thì không kẹt mãi ở "Đang khởi tạo"
          await Promise.race([
            new Promise((resolve) => {
              videoRef.current.onloadeddata = resolve;
            }),
            new Promise((resolve) => setTimeout(resolve, 8000)),
          ]);
        }
        // Gán luồng camera vào video hiển thị trực tiếp
        if (liveVideoRef.current) {
          liveVideoRef.current.srcObject = stream;
          liveVideoRef.current.play?.().catch(() => {});
        }

        if (cancelled) return;

        // 5. Đánh dấu hệ thống AI sẵn sàng và kích hoạt chu kỳ giám sát mỗi 300ms
        if (mountedRef.current) {
          setAiReady(true);
          setAiStatus("NORMAL");
        }

        detectionIntervalRef.current = setInterval(() => {
          if (!cancelled) runDetection();
        }, DETECTION_INTERVAL_MS);
      } catch (err) {
        console.error("Khởi tạo AI hoặc Camera thất bại:", err);
        if (mountedRef.current) {
          setAiInitError(
            "Không thể khởi tạo camera hoặc AI. Kiểm tra quyền camera, kết nối mạng và báo giảng viên nếu chưa khắc phục được.",
          );
        }
      }
    }

    initAI();

    // Dọn dẹp tài nguyên khi unmount component (tránh rò rỉ bộ nhớ)
    return () => {
      cancelled = true;
      mountedRef.current = false;

      if (detectionIntervalRef.current) {
        clearInterval(detectionIntervalRef.current);
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
      if (faceLandmarkerRef.current) {
        try {
          faceLandmarkerRef.current.close();
        } catch (e) {
          /* noop */
        }
      }
      if (objectDetectorRef.current) {
        try {
          objectDetectorRef.current.close();
        } catch (e) {
          /* noop */
        }
      }
    };
  }, [isExamStarted, runDetection]);

  // Đồng bộ lại thẻ video camera khi component re-render
  useEffect(() => {
    if (liveVideoRef.current && streamRef.current) {
      liveVideoRef.current.srcObject = streamRef.current;
    }
  });

  // ── Đếm ngược thời gian làm bài thi (Countdown Timer) ──
  // Tính theo MỐC KẾT THÚC (deadlineRef, dựa trên thời gian còn lại do server trả về lúc bấm "Bắt đầu")
  // thay vì trừ 1 mỗi giây: điện thoại làm chậm/ngưng setInterval khi ứng dụng xuống nền hoặc khóa màn hình,
  // trừ dần sẽ khiến đồng hồ chạy chậm. Có tính lại ngay khi ứng dụng quay lại (visibilitychange).
  const deadlineRef = useRef(null);
  useEffect(() => {
    if (!isExamStarted) return;
    const tick = () => {
      if (deadlineRef.current == null) return;
      setTimeLeft(
        Math.max(0, Math.ceil((deadlineRef.current - Date.now()) / 1000)),
      );
    };
    tick();
    const timer = setInterval(tick, 1000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [isExamStarted]);

  // Cờ "đang thi thật" cho callback báo vi phạm lockdown: không gửi vi phạm ở màn nhập mã / xem trước / kết quả
  useEffect(() => {
    examActiveRef.current = isExamStarted && !examResult;
  }, [isExamStarted, examResult]);

  // Hàm định dạng giây thành mm:ss
  const formatTime = useCallback((seconds) => {
    const m = Math.floor(seconds / 60)
      .toString()
      .padStart(2, "0");
    const s = (seconds % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  }, []);

  // Hợp nhất danh sách vi phạm từ AI và vi phạm Lockdown trình duyệt, sắp xếp mới nhất lên đầu
  const allViolations = useMemo(() => {
    const lockdownMapped = lockdownViolations.map((v) => ({
      id: v.id,
      time: v.timestamp,
      type: "LOCKDOWN",
      label: `🔒 ${v.type.replace(/_/g, " ")}`,
      message: v.message,
    }));
    return [...violationLogs, ...lockdownMapped]
      .sort((a, b) => b.id - a.id)
      .slice(0, 100);
  }, [violationLogs, lockdownViolations]);

  // ── Hàm tải đề thi sau khi phiên tham gia đã được duyệt ──
  const loadExam = useCallback(async (rawCode, tokenOverride) => {
    const code = (rawCode || "").trim();
    if (!code) {
      setExamLoadError("Vui lòng nhập mã đề thi");
      return null;
    }

    setExamLoading(true);
    setExamLoadError("");

    try {
      const activeToken =
        tokenOverride ||
        examSessionTokenRef.current ||
        sessionStorage.getItem("exam_session_token");
      if (!activeToken) {
        throw new Error("Phiên thi không hợp lệ. Vui lòng gửi lại yêu cầu vào thi.");
      }
      const headers = {};
      headers["X-Exam-Session"] = activeToken;

      const response = await fetch(
        `${API_BASE_URL}/exams/code/${encodeURIComponent(code)}/take`,
        { headers }
      );
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        // Backend trả lỗi rõ ràng bằng field "detail" (404 sai mã, 403 chưa mở/hết giờ...)
        throw new Error(
          data.detail || `Không thể tải đề thi (HTTP ${response.status})`,
        );
      }
      if (!Array.isArray(data.questions) || data.questions.length === 0) {
        throw new Error("Đề thi này chưa có câu hỏi hợp lệ nào");
      }

      let savedProgress = null;
      try {
        savedProgress = JSON.parse(
          sessionStorage.getItem("exam_progress") || "null",
        );
      } catch {
        sessionStorage.removeItem("exam_progress");
      }
      const matchingProgress =
        savedProgress?.exam_id === data.exam_id ? savedProgress : null;
      let examForSession = data;
      if (
        Array.isArray(matchingProgress?.question_order) &&
        matchingProgress.question_order.length === data.questions.length
      ) {
        const questionById = new Map(
          data.questions.map((question) => [String(question.id), question]),
        );
        const orderedQuestions = matchingProgress.question_order.map((id) =>
          questionById.get(String(id)),
        );
        if (orderedQuestions.every(Boolean)) {
          examForSession = { ...data, questions: orderedQuestions };
        }
      }
      const validQuestionIds = new Set(
        examForSession.questions.map((question) => question.id),
      );
      const restoredAnswers = Object.fromEntries(
        Object.entries(matchingProgress?.answers || {}).filter(
          ([questionId, option]) =>
            validQuestionIds.has(Number(questionId)) &&
            ["A", "B", "C", "D"].includes(option),
        ),
      );
      const restoredQuestion = Number(matchingProgress?.current_question);
      const restoredQuestionId = matchingProgress?.current_question_id;
      const questionIndexById = examForSession.questions.findIndex(
        (question) => String(question.id) === String(restoredQuestionId),
      );

      setExamData(examForSession);
      setTimeLeft(Math.max(1, examForSession.duration_minutes || 0) * 60);
      setCurrentQuestion(
        questionIndexById >= 0
          ? questionIndexById
          : Number.isInteger(restoredQuestion) &&
          restoredQuestion >= 0 &&
          restoredQuestion < examForSession.questions.length
          ? restoredQuestion
          : 0,
      );
      setAnswers(restoredAnswers);
      setSubmitError("");
      hasAutoSubmittedRef.current = false;
      return examForSession;
    } catch (err) {
      console.error("Lỗi tải đề thi:", err);
      setExamLoadError(
        err.message || "Không thể kết nối máy chủ, vui lòng thử lại",
      );
      return null;
    } finally {
      setExamLoading(false);
    }
  }, []);

  // ── Bấm "Bắt đầu làm bài": xin server ghi giờ bắt đầu và trả về thời gian CÒN LẠI ──
  const handleStartExam = useCallback(async () => {
    if (!examData || startingExam) return;
    setStartingExam(true);
    setStartError("");

    let remainingSeconds = Math.max(1, examData.duration_minutes || 0) * 60;
    try {
      const headers = { "Content-Type": "application/json" };
      headers["X-Exam-Session"] = examSessionTokenRef.current;
      const response = await fetch(
        `${API_BASE_URL}/exams/code/${encodeURIComponent(examData.exam_code)}/start`,
        {
          method: "POST",
          headers,
        },
      );
      const data = await response.json().catch(() => ({}));

      if (response.status === 409) {
        // Đã nộp bài trước đó — chuyển thẳng sang màn hình "đã nộp"
        sessionStorage.removeItem("exam_progress");
        sessionStorage.removeItem("exam_started");
        const result = { alreadySubmitted: true };
        sessionStorage.setItem("exam_result", JSON.stringify(result));
        setExamResult(result);
        setStartingExam(false);
        return;
      }
      if (response.status === 403 || response.status === 404) {
        // Đề chưa mở / đã hết giờ mở đề / không còn tồn tại: hiển thị lý do và không cho vào thi
        setStartError(data.detail || "Không thể bắt đầu bài thi này");
        setStartingExam(false);
        return;
      }
      if (response.ok && Number.isFinite(data.remaining_seconds)) {
        remainingSeconds = data.remaining_seconds;
      } else {
        throw new Error(
          data.detail || `Không thể bắt đầu bài thi (HTTP ${response.status})`,
        );
      }
    } catch (err) {
      setStartError(err.message || "Không thể bắt đầu bài thi. Vui lòng thử lại.");
      setStartingExam(false);
      return;
    }

    deadlineRef.current = Date.now() + remainingSeconds * 1000;
    sessionStorage.setItem("exam_started", "1");
    setTimeLeft(remainingSeconds);
    setStartingExam(false);
    setIsExamStarted(true);
  }, [examData, startingExam]);

  // ── Hàm nộp bài — dùng chung cho cả nộp chủ động (bấm nút) và tự động nộp khi hết giờ ──
  const handleSubmitExam = useCallback(
    async (autoSubmitted = false) => {
      if (!examData || submitting || examResult) return;

      setSubmitting(true);
      setSubmitError("");

      // Chuyển answers { [question.id]: 'A'|'B'|'C'|'D' } thành mảng đúng schema AnswerItem của backend
      const answerPayload = examData.questions.map((q) => ({
        question_id: q.id,
        selected_option: answers[q.id] || null,
      }));

      try {
        const headers = { "Content-Type": "application/json" };
        headers["X-Exam-Session"] = examSessionTokenRef.current;
        const response = await fetch(
          `${API_BASE_URL}/exams/code/${encodeURIComponent(examData.exam_code)}/submit`,
          {
            method: "POST",
            headers,
            body: JSON.stringify({
              answers: answerPayload,
              auto_submitted: autoSubmitted,
            }),
          },
        );
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
          // 409 = đã nộp bài trước đó rồi (ví dụ mở lại tab) — vẫn coi là kết thúc bài thi, không phải lỗi chặn
          if (response.status === 409) {
            sessionStorage.removeItem("exam_progress");
            sessionStorage.removeItem("exam_started");
            const result = { alreadySubmitted: true };
            sessionStorage.setItem("exam_result", JSON.stringify(result));
            setExamResult(result);
            return;
          }
          throw new Error(
            data.detail || `Nộp bài thất bại (HTTP ${response.status})`,
          );
        }

        sessionStorage.removeItem("exam_progress");
        sessionStorage.removeItem("exam_started");
        sessionStorage.setItem("exam_result", JSON.stringify(data));
        setExamResult(data);
      } catch (err) {
        console.error("Lỗi nộp bài:", err);
        setSubmitError(
          err.message || "Không thể kết nối máy chủ, vui lòng thử lại",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [examData, answers, submitting, examResult],
  );

  // ── Tự động nộp bài khi hết giờ làm bài (đúng yêu cầu FR-03 đặc tả: "không để mất dữ liệu
  // đã chọn" khi hết thời gian) — hasAutoSubmittedRef chặn gọi 2 lần do React StrictMode
  // chạy effect 2 lần ở môi trường dev. Đặt SAU khai báo handleSubmitExam để tránh cảnh báo
  // "đọc biến trong lúc đang khởi tạo" từ React Compiler/eslint dù không gây lỗi runtime thật.
  useEffect(() => {
    if (!isExamStarted || !examData || examResult) return;
    if (timeLeft === 0 && !hasAutoSubmittedRef.current) {
      hasAutoSubmittedRef.current = true;
      handleSubmitExam(true);
    }
  }, [timeLeft, isExamStarted, examData, examResult, handleSubmitExam]);

  // ── Các hàm thao tác điều hướng câu hỏi và chọn đáp án ──
  const goToQuestion = useCallback(
    (index) => {
      if (examData && index >= 0 && index < examData.questions.length)
        setCurrentQuestion(index);
    },
    [examData],
  );

  // Lưu đáp án theo question.id (không phải theo index) để khớp thẳng với payload API khi nộp bài
  const selectAnswer = useCallback((questionId, optionLetter) => {
    setAnswers((prev) => ({ ...prev, [questionId]: optionLetter }));
  }, []);

  useEffect(() => {
    if (!isExamStarted || !examData || !examSessionToken) return;
    sessionStorage.setItem(
      "exam_progress",
      JSON.stringify({
        exam_id: examData.exam_id,
        exam_code: examData.exam_code,
        answers,
        current_question: currentQuestion,
        current_question_id: examData.questions[currentQuestion]?.id,
        question_order: examData.questions.map((question) => question.id),
        saved_at: Date.now(),
      }),
    );
  }, [
    isExamStarted,
    examData,
    examSessionToken,
    answers,
    currentQuestion,
    timeLeft,
  ]);

  // ── Giai đoạn C: Tải danh sách đề thi khả dụng & xử lý xin vào thi ──
  const fetchAvailableExams = useCallback(async () => {
    try {
      setLoadingAvailable(true);
      setAvailableError("");
      const res = await fetch(`${API_BASE_URL}/exams/available`);
      if (!res.ok) throw new Error(`Lỗi tải danh mục đề thi (HTTP ${res.status})`);
      const data = await res.json();
      const subjects = Array.isArray(data) ? data : data.subjects || [];
      setAvailableData(subjects);
      setSelectedSubject((current) =>
        subjects.some((item) => item.subject === current)
          ? current
          : "",
      );
      setSelectedExamChoice((current) => {
        if (!current) return null;
        const found = subjects.some((item) =>
          item.exams?.some((exam) => exam.exam_id === current.exam_id),
        );
        return found ? current : null;
      });
    } catch (err) {
      console.error("Lỗi tải đề thi khả dụng:", err);
      setAvailableError(err.message || "Không thể tải danh sách đề thi");
    } finally {
      setLoadingAvailable(false);
    }
  }, []);

  useEffect(() => {
    fetchAvailableExams();
    const refreshTimer = setInterval(fetchAvailableExams, 30000);
    return () => clearInterval(refreshTimer);
  }, [fetchAvailableExams]);

  // Gửi yêu cầu xin vào phòng thi
  const handleJoinRequest = useCallback(
    async (exam) => {
      setSelectedExamInfo(exam);
      setExamLoadError("");
      setExamLoading(true);
      try {
        const headers = { "Content-Type": "application/json" };
        const currentRequestToken = requestToken;
        if (currentRequestToken) {
          headers["X-Request-Token"] = currentRequestToken;
        }
        const res = await fetch(`${API_BASE_URL}/exams/${exam.exam_id}/join-request`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            student_id: studentId,
            student_name: studentName,
            device_info: navigator.userAgent,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || `Không thể xin vào thi (HTTP ${res.status})`);
        }
        const nextRequestToken = data.request_token || currentRequestToken;
        if (!nextRequestToken) {
          throw new Error("Máy chủ không cấp mã yêu cầu vào thi.");
        }
        if (data.request_token) {
          setExamSessionToken("");
          examSessionTokenRef.current = "";
          sessionStorage.removeItem("exam_started");
          sessionStorage.removeItem("exam_result");
          sessionStorage.removeItem("exam_progress");
          setExamResult(null);
        }
        setRequestToken(nextRequestToken);
        const examInfo = {
          ...exam,
          title: data.exam_title || exam.title,
          exam_code: data.exam_code || exam.exam_code,
        };
        setSelectedExamInfo(examInfo);

        if (data.status === "APPROVED") {
          const activeToken = examSessionTokenRef.current;
          if (!activeToken) {
            setExamLoadError("Phiên thi đã được duyệt ở thiết bị khác. Hãy gửi lại yêu cầu từ thiết bị này.");
            setEnrollmentState(null);
            return;
          }
          setEnrollmentState("APPROVED");
          await loadExam(examInfo.exam_code, activeToken);
        } else if (data.status === "PENDING") {
          setEnrollmentState("PENDING");
        } else if (data.status === "REJECTED") {
          setEnrollmentState("REJECTED");
          setRequestToken("");
          setExamSessionToken("");
          setRejectReason(data.reject_reason || "Giảng viên đã từ chối yêu cầu vào phòng thi.");
        }
      } catch (err) {
        setExamLoadError(err.message || "Không thể kết nối máy chủ");
      } finally {
        setExamLoading(false);
      }
    },
    [studentId, studentName, loadExam, requestToken]
  );

  const handleCancelJoinRequest = useCallback(async () => {
    if (!requestToken || cancelingJoinRequest) return;
    setCancelingJoinRequest(true);
    setExamLoadError("");
    try {
      const response = await fetch(`${API_BASE_URL}/exams/join-request/cancel`, {
        method: "POST",
        headers: { "X-Request-Token": requestToken },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || `Không thể hủy yêu cầu (HTTP ${response.status})`);
      }
      setRequestToken("");
      setExamSessionToken("");
      examSessionTokenRef.current = "";
      sessionStorage.removeItem("exam_started");
      setEnrollmentState(null);
      setSelectedExamInfo(null);
    } catch (err) {
      setExamLoadError(err.message || "Không thể hủy yêu cầu vào thi.");
    } finally {
      setCancelingJoinRequest(false);
    }
  }, [requestToken, cancelingJoinRequest]);

  // Poll cả yêu cầu đang chờ lẫn phiên đã duyệt để phát hiện giảng viên thu hồi quyền.
  useEffect(() => {
    if (
      !["PENDING", "APPROVED"].includes(enrollmentState) ||
      !requestToken ||
      examResult
    ) {
      return;
    }

    let isMounted = true;
    const pollTimer = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/exams/join-request/status`, {
          headers: { "X-Request-Token": requestToken },
        });
        if (!res.ok) {
          if (res.status === 401 || res.status === 403) {
            clearInterval(pollTimer);
            setRequestToken("");
            setEnrollmentState(enrollmentState === "APPROVED" ? "REVOKED" : null);
            setExamSessionToken("");
            if (enrollmentState === "APPROVED") {
              setIsExamStarted(false);
              setExamData(null);
              sessionStorage.removeItem("exam_progress");
              sessionStorage.removeItem("exam_started");
            }
            setExamLoadError("Phiên yêu cầu không còn hợp lệ. Vui lòng gửi lại yêu cầu vào thi.");
          }
          return;
        }
        const data = await res.json();
        if (!isMounted) return;

        if (data.status === "APPROVED") {
          if (data.exam_session_token) {
            setExamSessionToken(data.exam_session_token);
            setEnrollmentState("APPROVED");
            const examInfo = selectedExamInfo
              ? {
                  ...selectedExamInfo,
                  exam_code: selectedExamInfo.exam_code || data.exam_code,
                  title: selectedExamInfo.title || data.exam_title,
                }
              : null;
            if (examInfo) {
              setSelectedExamInfo(examInfo);
              await loadExam(examInfo.exam_code, data.exam_session_token);
            }
          }
        } else if (data.status === "REJECTED") {
          setEnrollmentState("REJECTED");
          setRequestToken("");
          setExamSessionToken("");
          setRejectReason(data.reject_reason || "Giảng viên đã từ chối yêu cầu vào phòng thi.");
        } else if (data.status === "REVOKED") {
          setExamSessionToken("");
          setEnrollmentState("REVOKED");
          setIsExamStarted(false);
          setExamData(null);
          sessionStorage.removeItem("exam_progress");
          sessionStorage.removeItem("exam_started");
        }
      } catch (err) {
        console.warn("Lỗi kiểm tra trạng thái duyệt:", err);
      }
    }, 3000);

    return () => {
      isMounted = false;
      clearInterval(pollTimer);
    };
  }, [enrollmentState, requestToken, selectedExamInfo, loadExam, examResult]);

  useEffect(() => {
    if (!examSessionToken || !selectedExamInfo?.exam_code) return undefined;

    let isMounted = true;
    const resumeSession = async () => {
      const loadedExam = await loadExam(
        selectedExamInfo.exam_code,
        examSessionToken,
      );
      if (!loadedExam || !isMounted || sessionStorage.getItem("exam_started") !== "1") {
        return;
      }

      try {
        const response = await fetch(
          `${API_BASE_URL}/exams/code/${encodeURIComponent(loadedExam.exam_code)}/start`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Exam-Session": examSessionToken,
            },
          },
        );
        const data = await response.json().catch(() => ({}));
        if (!isMounted) return;
        if (response.status === 409) {
          setExamResult({ alreadySubmitted: true });
          return;
        }
        if (!response.ok || !Number.isFinite(data.remaining_seconds)) {
          if (response.status === 401 || response.status === 403) {
            setEnrollmentState("REVOKED");
            setExamSessionToken("");
            setIsExamStarted(false);
            setExamData(null);
            sessionStorage.removeItem("exam_progress");
            sessionStorage.removeItem("exam_started");
            return;
          }
          throw new Error(data.detail || `Không thể khôi phục phiên thi (HTTP ${response.status})`);
        }

        deadlineRef.current = Date.now() + data.remaining_seconds * 1000;
        setTimeLeft(data.remaining_seconds);
        setIsExamStarted(true);
      } catch (err) {
        if (isMounted) {
          setExamLoadError(err.message || "Không thể khôi phục phiên thi.");
        }
      }
    };

    resumeSession();
    return () => {
      isMounted = false;
    };
  }, [examSessionToken, selectedExamInfo?.exam_code, loadExam]);

  // Câu hỏi hiện tại đang hiển thị (chỉ có giá trị khi đã tải đề thành công)
  const question = examData?.questions?.[currentQuestion] || null;
  const selectedSubjectData = availableData.find(
    (item) => item.subject === selectedSubject,
  );

  // ═══════════════════════════════════════════════════════════════════════
  // MÀN HÌNH A — KẾT QUẢ SAU KHI NỘP BÀI (ưu tiên cao nhất)
  // ═══════════════════════════════════════════════════════════════════════
  if (examResult) {
    const already = examResult.alreadySubmitted;
    const passed = examResult.passed;
    return (
      <StudentGateway
        studentId={studentId}
        studentName={studentName}
        stage={3}
      >
        <div className="glass-card w-full max-w-md p-8 sm:p-10 text-center space-y-6">
          {already ? (
            <>
              <div className="w-16 h-16 mx-auto rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center">
                <AlertTriangle className="w-8 h-8 text-amber-700" />
              </div>
              <h1 className="text-2xl font-bold">Bạn đã nộp bài trước đó</h1>
              <p className="text-text-secondary leading-relaxed">
                Hệ thống ghi nhận sinh viên{" "}
                <span className="font-mono text-text-primary">{studentId}</span>{" "}
                đã hoàn thành đề thi này rồi — mỗi đề chỉ được nộp bài đúng 1
                lần.
              </p>
            </>
          ) : (
            <>
              <div
                className={`w-16 h-16 mx-auto rounded-2xl flex items-center justify-center border ${
                  passed
                    ? "bg-green-500/10 border-green-500/30"
                    : "bg-red-500/10 border-red-500/30"
                }`}
              >
                {passed ? (
                  <Trophy className="w-8 h-8 text-green-700" />
                ) : (
                  <XCircle className="w-8 h-8 text-red-700" />
                )}
              </div>
              <div>
                <p className="text-xs text-text-muted uppercase tracking-wider font-semibold">
                  Điểm số của bạn
                </p>
                <p
                  className={`text-6xl font-bold mt-2 ${passed ? "text-green-700" : "text-red-700"}`}
                >
                  {Number(examResult.total_score ?? 0).toFixed(2)}
                  <span className="text-2xl text-text-muted font-normal">
                    /10
                  </span>
                </p>
              </div>
              <div className="flex flex-wrap items-center justify-center gap-3 text-sm">
                <span className="text-text-secondary">
                  {examResult.correct_count}/{examResult.total_questions} câu
                  đúng
                </span>
                <span
                  className={`px-3 py-1 rounded-full font-semibold ${
                    passed
                      ? "bg-green-500/10 text-green-700"
                      : "bg-red-500/10 text-red-700"
                  }`}
                >
                  {passed ? "Đạt" : "Không đạt"} · điểm đạt{" "}
                  {examResult.pass_score}
                </span>
              </div>
              {examResult.status === "AUTO_SUBMITTED" && (
                <p className="text-xs text-amber-700">
                  ⏱️ Bài thi đã được hệ thống tự động nộp khi hết giờ làm bài.
                </p>
              )}
            </>
          )}
          <button
            onClick={onLogout}
            className="w-full py-3 rounded-xl font-bold text-white bg-accent-cyan
                       hover:brightness-95 shadow-sm transition-all cursor-pointer
                       flex items-center justify-center gap-2"
          >
            <LogOut className="w-4 h-4" /> Đăng xuất
          </button>
        </div>
      </StudentGateway>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════
  // MÀN HÌNH B1 — ĐANG CHỜ GIẢNG VIÊN DUYỆT (PENDING)
  // ═══════════════════════════════════════════════════════════════════════
  if (enrollmentState === "PENDING") {
    return (
      <StudentGateway
        studentId={studentId}
        studentName={studentName}
        stage={2}
      >
        <div className="glass-card w-full max-w-md p-8 sm:p-10 space-y-6 text-center">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center animate-pulse">
            <Hourglass className="w-8 h-8 text-amber-700 animate-spin" />
          </div>

          <div className="space-y-2">
            <h1 className="text-xl font-bold text-text-primary">
              Đang chờ Giảng viên phê duyệt...
            </h1>
            <p className="text-sm text-text-muted">
              Yêu cầu tham gia phòng thi của bạn đã được gửi tới giám thị. Vui lòng giữ nguyên màn hình này.
            </p>
          </div>

          {selectedExamInfo && (
            <div className="bg-bg-card border border-border-default rounded-2xl p-4 text-left space-y-2">
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span>Môn học:</span>
                <span className="font-semibold text-text-primary">
                  {selectedExamInfo.subject || "Chung"}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span>Đề thi:</span>
                <span className="font-semibold text-text-primary">
                  {selectedExamInfo.title}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span>Giảng viên:</span>
                <span className="font-semibold text-text-primary">
                  {selectedExamInfo.teacher_name || "Giảng viên"}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span>Mã đề:</span>
                <span className="font-mono font-bold text-accent-cyan">
                  {selectedExamInfo.exam_code}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span>Mã sinh viên:</span>
                <span className="font-mono text-text-primary">{studentId}</span>
              </div>
            </div>
          )}

          <div className="flex items-center justify-center gap-2 text-xs text-amber-700 bg-amber-500/10 border border-amber-500/30 rounded-xl p-3">
            <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" />
            <span>Hệ thống tự động kiểm tra mỗi 3 giây...</span>
          </div>

          {examLoadError && (
            <p className="text-sm text-red-700" role="alert">{examLoadError}</p>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
              onClick={handleCancelJoinRequest}
              disabled={cancelingJoinRequest}
              className="min-h-12 py-2.5 rounded-xl text-sm font-semibold text-text-secondary border border-border-default hover:bg-bg-card-hover transition-colors cursor-pointer disabled:opacity-50"
            >
              {cancelingJoinRequest ? "Đang hủy yêu cầu..." : "Hủy yêu cầu"}
            </button>
            <button
              onClick={onLogout}
              className="min-h-12 py-2.5 rounded-xl text-sm font-semibold bg-bg-card border border-border-default text-text-secondary hover:bg-bg-card-hover transition-colors cursor-pointer"
            >
              Thoát
            </button>
          </div>
        </div>
      </StudentGateway>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════
  // MÀN HÌNH B2 — BỊ GIẢNG VIÊN TỪ CHỐI (REJECTED)
  // ═══════════════════════════════════════════════════════════════════════
  if (enrollmentState === "REJECTED") {
    return (
      <StudentGateway
        studentId={studentId}
        studentName={studentName}
        stage={1}
      >
        <div className="glass-card w-full max-w-md p-8 sm:p-10 space-y-6 text-center">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-red-500/10 border border-red-500/30 flex items-center justify-center">
            <XCircle className="w-8 h-8 text-red-700" />
          </div>

          <div className="space-y-2">
            <h1 className="text-xl font-bold text-red-700">
              Yêu cầu vào thi bị từ chối
            </h1>
            <p className="text-sm text-text-muted">
              Giảng viên / Giám thị phòng thi không duyệt yêu cầu tham gia của bạn.
            </p>
          </div>

          {rejectReason && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-left">
              <p className="text-xs font-semibold text-red-700 uppercase mb-1">
                Lý do từ chối:
              </p>
              <p className="text-sm text-red-700 leading-relaxed">
                {rejectReason}
              </p>
            </div>
          )}

          <button
            onClick={() => {
              setEnrollmentState(null);
              setRequestToken("");
              setExamSessionToken("");
              examSessionTokenRef.current = "";
              sessionStorage.removeItem("exam_started");
              sessionStorage.removeItem("exam_progress");
              setRejectReason("");
              setSelectedExamInfo(null);
            }}
            className="w-full py-3 rounded-xl font-bold text-white bg-accent-cyan hover:brightness-95 shadow-sm transition-all cursor-pointer flex items-center justify-center gap-2"
          >
            <ArrowLeft className="w-4 h-4" /> Quay lại chọn đề khác
          </button>
        </div>
      </StudentGateway>
    );
  }

  if (enrollmentState === "REVOKED") {
    return (
      <StudentGateway studentId={studentId} studentName={studentName} stage={2}>
        <div className="glass-card w-full max-w-md p-8 sm:p-10 space-y-5 text-center">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-red-500/10 border border-red-500/30 flex items-center justify-center">
            <Shield className="w-8 h-8 text-red-700" />
          </div>
          <h1 className="text-xl font-bold text-red-700">
            Phiên thi đã bị thu hồi
          </h1>
          <p className="text-sm text-text-secondary leading-relaxed">
            Giảng viên đã thu hồi quyền tham gia. Bạn không thể tiếp tục bài thi
            này. Hãy liên hệ giảng viên nếu cần hỗ trợ.
          </p>
          {selectedExamInfo && (
            <p className="text-sm text-text-muted">
              {selectedExamInfo.subject} · {selectedExamInfo.title}
            </p>
          )}
          <button
            onClick={() => {
              setEnrollmentState(null);
              setRequestToken("");
              setExamSessionToken("");
              examSessionTokenRef.current = "";
              setExamData(null);
              setSelectedExamInfo(null);
              sessionStorage.removeItem("exam_started");
              sessionStorage.removeItem("exam_progress");
            }}
            className="w-full min-h-12 py-3 rounded-xl font-bold text-white bg-accent-cyan hover:brightness-95 transition-all cursor-pointer"
          >
            Quay lại danh sách đề thi
          </button>
          <button
            onClick={onLogout}
            className="w-full min-h-12 py-3 rounded-xl text-sm font-semibold text-text-secondary border border-border-default hover:bg-bg-card-hover transition-colors cursor-pointer"
          >
            Thoát
          </button>
        </div>
      </StudentGateway>
    );
  }

  if (enrollmentState === "APPROVED" && !examData) {
    return (
      <StudentGateway studentId={studentId} studentName={studentName} stage={2}>
        <div className="glass-card w-full max-w-md p-8 text-center space-y-4">
          <Loader2 className="w-10 h-10 mx-auto animate-spin text-accent-cyan" />
          <h1 className="text-xl font-bold">Đang mở phiên thi</h1>
          <p className="text-sm text-text-muted">
            Phiên đã được duyệt. Đang tải thông tin đề thi...
          </p>
          {examLoadError && (
            <p className="text-sm text-red-700" role="alert">{examLoadError}</p>
          )}
          <button
            onClick={onLogout}
            className="w-full min-h-12 rounded-xl border border-border-default text-text-secondary"
          >
            Thoát
          </button>
        </div>
      </StudentGateway>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════
  // MÀN HÌNH B — CHỌN MÔN / ĐỀ THI
  // ═══════════════════════════════════════════════════════════════════════
  if (!examData) {
    return (
      <StudentGateway
        studentId={studentId}
        studentName={studentName}
        stage={examResult ? 3 : examData ? 2 : 1}
      >
        <div className="glass-card w-full max-w-xl p-6 sm:p-8 space-y-6">
          <div className="flex items-center justify-between pb-3 border-b border-border-default">
            <div>
              <h1 className="text-xl font-bold text-text-primary">
                Danh mục Đề thi khả dụng
              </h1>
              <p className="text-xs text-text-muted mt-0.5">
                {studentName ? `${studentName} • ` : ""}Mã SV:{" "}
                <span className="font-mono text-text-primary font-semibold">
                  {studentId}
                </span>
              </p>
            </div>
            <button
              onClick={fetchAvailableExams}
              disabled={loadingAvailable}
              className="p-2 rounded-xl bg-bg-card border border-border-default hover:bg-bg-card-hover transition-colors text-text-secondary cursor-pointer"
              title="Làm mới danh sách"
            >
              <RefreshCw
                className={`w-4 h-4 ${loadingAvailable ? "animate-spin" : ""}`}
              />
            </button>
          </div>

          {examLoadError && (
            <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
              <AlertTriangle className="w-4 h-4 text-red-700 flex-shrink-0 mt-0.5" />
              <p className="text-red-700 text-sm leading-relaxed">
                {examLoadError}
              </p>
            </div>
          )}

          {availableError && (
            <div className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3">
              <AlertTriangle className="w-4 h-4 text-amber-700 flex-shrink-0 mt-0.5" />
              <p className="text-amber-700 text-sm leading-relaxed">
                {availableError}
              </p>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <label className="space-y-2">
              <span className="block text-sm font-semibold text-text-primary">
                Bước 1 · Chọn môn thi
              </span>
              <select
                value={selectedSubject}
                onChange={(event) => {
                  setSelectedSubject(event.target.value);
                  setSelectedExamChoice(null);
                }}
                disabled={availableData.length === 0}
                className="w-full min-h-12 rounded-xl px-3 bg-bg-card border border-border-default text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-cyan disabled:opacity-60"
              >
                <option value="">Chọn môn học</option>
                {availableData.map((item) => (
                  <option key={item.subject} value={item.subject}>
                    {item.subject}
                  </option>
                ))}
              </select>
            </label>
            <div className="space-y-2">
              <span className="block text-sm font-semibold text-text-primary">
                Bước 2 · Chọn đề thi
              </span>
              <p className="min-h-12 flex items-center rounded-xl px-3 bg-bg-card border border-border-default text-sm text-text-secondary">
                {selectedSubject || "Vui lòng chọn môn trước"}
              </p>
            </div>
          </div>

          <div className="space-y-3 max-h-[440px] overflow-y-auto pr-1">
            {loadingAvailable && availableData.length === 0 ? (
              <div className="py-10 text-center text-text-muted flex flex-col items-center gap-2">
                <Loader2 className="w-6 h-6 animate-spin text-accent-cyan" />
                <span>Đang tải danh sách đề thi...</span>
              </div>
            ) : availableData.length === 0 ? (
              <div className="py-8 text-center text-text-muted bg-bg-card rounded-2xl border border-border-default p-6 space-y-2">
                <FileQuestion className="w-8 h-8 mx-auto text-text-muted/60" />
                <p className="font-medium text-text-primary">
                  Hiện chưa có đề thi nào đang mở
                </p>
              </div>
            ) : (
              selectedSubjectData?.exams.length ? (
                selectedSubjectData.exams.map((exam) => {
                  const isSelected =
                    selectedExamChoice?.exam_id === exam.exam_id;
                  const formatDate = (value) =>
                    new Date(
                      value.endsWith("Z") ? value : `${value}Z`,
                    ).toLocaleString("vi-VN", {
                      timeZone: "Asia/Ho_Chi_Minh",
                      dateStyle: "short",
                      timeStyle: "short",
                    });
                  return (
                    <button
                      key={exam.exam_id}
                      type="button"
                      role="radio"
                      aria-checked={isSelected}
                      onClick={() => setSelectedExamChoice(exam)}
                      className={`w-full min-h-24 rounded-2xl p-4 text-left border transition-colors ${
                        isSelected
                          ? "border-accent-cyan bg-cyan-500/10 ring-2 ring-accent-cyan/30"
                          : "border-border-default bg-bg-card hover:border-accent-cyan/50"
                      }`}
                    >
                      <span className="flex items-start justify-between gap-3">
                        <span className="font-bold text-base text-text-primary">
                          {exam.title}
                        </span>
                        <span
                          className={`mt-1 w-5 h-5 rounded-full border-2 flex-shrink-0 ${
                            isSelected
                              ? "border-accent-cyan bg-accent-cyan ring-2 ring-cyan-200"
                              : "border-border-default"
                          }`}
                        />
                      </span>
                      <span className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-xs text-text-muted">
                        <span>Giảng viên: {exam.teacher_name}</span>
                        <span>
                          Thời lượng: {exam.duration_minutes} phút ·{" "}
                          {exam.total_questions} câu
                        </span>
                        <span>Mở: {formatDate(exam.start_time)}</span>
                        <span>Đóng: {formatDate(exam.end_time)}</span>
                      </span>
                    </button>
                  );
                })
              ) : (
                <p className="rounded-xl border border-border-default bg-bg-card p-4 text-sm text-text-muted">
                  Chọn môn thi để xem các đề đang mở.
                </p>
              )
            )}
          </div>

          <div className="pt-2 flex flex-col-reverse sm:flex-row sm:items-center justify-between gap-3">
            <button
              onClick={onLogout}
              className="min-h-12 px-4 text-sm text-text-muted hover:text-text-primary transition-colors cursor-pointer flex items-center justify-center gap-1"
            >
              <LogOut className="w-4 h-4" /> Thoát
            </button>
            <button
              type="button"
              onClick={() =>
                handleJoinRequest({
                  ...selectedExamChoice,
                  subject: selectedSubject,
                })
              }
              disabled={!selectedExamChoice || examLoading}
              className="min-h-12 px-5 rounded-xl text-sm font-bold text-white bg-accent-cyan hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer flex items-center justify-center gap-2"
            >
              {examLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Đang gửi yêu cầu...
                </>
              ) : (
                "Xin vào thi"
              )}
            </button>
          </div>
        </div>
      </StudentGateway>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════
  // MÀN HÌNH C — ĐÃ TẢI ĐỀ, XEM TRƯỚC & XÁC NHẬN BẮT ĐẦU
  // (Camera/AI + đồng hồ đếm ngược chỉ thật sự kích hoạt SAU màn hình này, khi isExamStarted = true)
  // ═══════════════════════════════════════════════════════════════════════
  if (!isExamStarted) {
    return (
      <StudentGateway
        studentId={studentId}
        studentName={studentName}
        stage={examResult ? 3 : examData ? 2 : 1}
      >
        <div className="glass-card exam-ready-card w-full max-w-lg p-8 sm:p-10 space-y-6">
          <div className="text-center space-y-3">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center">
              <Shield className="w-7 h-7 text-accent-cyan" />
            </div>
            <p className="text-sm text-accent-cyan font-semibold uppercase tracking-wide">
              Mã đề: {examData.exam_code}
            </p>
            <h1 className="text-2xl font-bold text-text-primary">
              {examData.title}
            </h1>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="bg-bg-card border border-border-default rounded-2xl p-4 text-center">
              <p className="text-xs text-text-muted uppercase tracking-wide">
                Số câu hỏi
              </p>
              <p className="text-2xl font-bold mt-1 text-text-primary">
                {examData.questions.length}
              </p>
            </div>
            <div className="bg-bg-card border border-border-default rounded-2xl p-4 text-center">
              <p className="text-xs text-text-muted uppercase tracking-wide">
                Thời gian làm bài
              </p>
              <p className="text-2xl font-bold mt-1 text-text-primary">
                {examData.duration_minutes} phút
              </p>
            </div>
          </div>

          <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 text-sm text-amber-700 space-y-1.5">
            <p className="font-semibold flex items-center gap-1.5">
              <AlertTriangle className="w-4 h-4" /> Lưu ý trước khi bắt đầu:
            </p>
            <ul className="list-disc list-inside space-y-1 text-amber-700/90 pl-1">
              <li>
                Cần cho phép truy cập Camera để hệ thống giám sát hoạt động
              </li>
              <li>
                Đồng hồ đếm ngược bắt đầu chạy ngay khi bấm "Bắt đầu làm bài"
              </li>
              <li>Mỗi đề thi chỉ được nộp bài đúng 1 lần duy nhất</li>
            </ul>
          </div>

          {startError && (
            <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
              <AlertTriangle className="w-4 h-4 text-red-700 flex-shrink-0 mt-0.5" />
              <p className="text-red-700 text-sm leading-relaxed">{startError}</p>
            </div>
          )}

          <button
            onClick={handleStartExam}
            disabled={startingExam}
            className="w-full py-3.5 rounded-xl font-bold text-white bg-accent-cyan
                       hover:brightness-95 shadow-sm active:scale-[0.99]
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-all cursor-pointer flex items-center justify-center gap-2"
          >
            {startingExam ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" /> Đang bắt đầu...
              </>
            ) : (
              "Bắt đầu làm bài"
            )}
          </button>
          <button
            onClick={() => {
              setStartError("");
              setExamData(null);
            }}
            className="w-full text-center text-sm text-text-muted hover:text-text-primary transition-colors cursor-pointer"
          >
            ← Nhập mã đề khác
          </button>
        </div>
      </StudentGateway>
    );
  }

  return (
    <div className="exam-workspace min-h-dvh bg-bg-primary text-text-primary flex flex-col select-none">
      {/* Các thẻ Video và Canvas ngầm phục vụ trích xuất dữ liệu phân tích AI.
          KHÔNG dùng display:none (class "hidden") cho video: iOS Safari không phát/giải mã khung hình
          của video bị display:none, khiến AI không nhận được ảnh. Thay bằng phần tử 1×1px trong suốt. */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        aria-hidden="true"
        style={{
          position: "fixed",
          left: 0,
          top: 0,
          width: 1,
          height: 1,
          opacity: 0,
          pointerEvents: "none",
        }}
      />
      <canvas ref={canvasRef} width="320" height="240" className="hidden" />

      {/* ═══ MODAL CẢNH BÁO: RỜI CỬA SỔ / CHUYỂN TAB TRÌNH DUYỆT ═══ */}
      <AnimatePresence>
        {showBlurOverlay && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[9999] overlay-backdrop flex items-center justify-center"
          >
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.8, opacity: 0 }}
              className="glass-card p-6 sm:p-10 mx-4 max-w-lg text-center space-y-6 border-red-500/50"
            >
              <div className="w-24 h-24 mx-auto rounded-full bg-red-500/20 flex items-center justify-center">
                <AlertTriangle className="w-12 h-12 text-red-500" />
              </div>
              <h2 className="text-3xl font-bold text-red-700">
                CẢNH BÁO VI PHẠM
              </h2>
              <p className="text-lg text-text-primary leading-relaxed">
                Hệ thống phát hiện bạn vừa <strong>chuyển tab</strong> hoặc{" "}
                <strong>click ra ngoài</strong> cửa sổ bài thi!
              </p>
              <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-base text-red-700 font-bold">
                Số lần vi phạm: {tabSwitchCount}
              </div>
              <p className="text-sm text-text-secondary">
                Nếu tiếp tục vi phạm, bài thi sẽ tự động bị hủy.
              </p>
              <button
                onClick={dismissBlurOverlay}
                className="w-full py-4 px-6 rounded-xl bg-red-600 text-white font-bold text-lg 
                           hover:bg-red-500 active:scale-[0.98] transition-all cursor-pointer"
              >
                Tôi đã hiểu &amp; Quay lại bài thi
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ═══ MODAL CẢNH BÁO: BẮT BUỘC CHẾ ĐỘ TOÀN MÀN HÌNH (FULLSCREEN) ═══ */}
      <AnimatePresence>
        {showFullscreenOverlay && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[9999] overlay-backdrop flex items-center justify-center"
          >
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.8, opacity: 0 }}
              className="glass-card p-6 sm:p-10 mx-4 max-w-lg text-center space-y-6"
            >
              <div className="w-20 h-20 mx-auto rounded-full bg-red-500/20 flex items-center justify-center">
                <Maximize className="w-10 h-10 text-red-700" />
              </div>
              <h2 className="text-2xl font-bold text-text-primary">
                Chế độ Toàn màn hình bắt buộc
              </h2>
              <p className="text-text-secondary leading-relaxed">
                Bạn đã thoát khỏi chế độ toàn màn hình. Vui lòng nhấn nút bên
                dưới để tiếp tục làm bài.
              </p>
              {tabSwitchCount > 0 && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 text-sm text-red-700">
                  ⚠️ Bạn đã chuyển tab/thoát fullscreen {tabSwitchCount} lần
                </div>
              )}
              <button
                onClick={requestFullscreen}
                className="w-full py-3.5 px-6 rounded-xl bg-accent-cyan text-white font-bold text-lg 
                           hover:bg-cyan-400 active:scale-[0.98] transition-all duration-200 cursor-pointer"
              >
                <Maximize className="w-5 h-5 inline mr-2 -mt-0.5" />
                Quay lại Toàn màn hình
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Đường viền Gradient trang trí thanh tiêu đề */}
      <div className="gradient-line w-full" />

      {/* ═══ THANH TIÊU ĐỀ PHÒNG THI (HEADER) ═══ */}
      <header className="bg-bg-secondary/80 backdrop-blur-xl border-b border-border-default px-4 lg:px-6 py-3">
        <div className="w-full flex items-center justify-between flex-wrap gap-3">
          {/* Logo và Thông tin sinh viên */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-accent-cyan flex items-center justify-center shadow-sm">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-base lg:text-lg text-text-primary tracking-tight">
                  EduShield AI
                </span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-accent-cyan border border-cyan-500/30 font-semibold">
                  PHÒNG THI
                </span>
              </div>
              <p className="text-xs text-text-muted hidden sm:block mt-0.5">
                {studentName ? (
                  <>
                    <span className="text-text-secondary font-medium">
                      {studentName}
                    </span>
                    <span className="mx-1.5 text-text-muted/50">•</span>
                    Mã SV:{" "}
                    <span className="font-mono text-text-secondary">
                      {studentId}
                    </span>
                  </>
                ) : (
                  <>
                    Mã thí sinh: <span className="font-mono">{studentId}</span>
                  </>
                )}
              </p>
            </div>
          </div>

          {/* Khu vực trung tâm: Đồng hồ đếm ngược & Tiến độ câu hỏi */}
          <div className="flex items-center gap-4 order-3 lg:order-2 w-full lg:w-auto justify-center">
            {/* Đồng hồ đếm ngược */}
            <div className="flex items-center gap-2 bg-bg-card/80 border border-border-default rounded-2xl px-4 py-2">
              <Clock className="w-4 h-4 text-text-muted" />
              <span className="text-sm text-text-secondary">Còn lại</span>
              <span
                className={`font-mono font-bold text-lg tabular-nums ${
                  timeLeft < 300 ? "timer-urgent" : "text-accent-amber"
                }`}
              >
                {formatTime(timeLeft)}
              </span>
            </div>

            {/* Tiến độ câu trả lời */}
            <div className="flex items-center gap-2 bg-bg-card/80 border border-border-default rounded-2xl px-4 py-2">
              <ScrollText className="w-4 h-4 text-text-muted" />
              <span className="text-sm text-text-secondary">Tiến độ</span>
              <span className="font-bold text-accent-cyan">
                {answeredCount}/{totalQuestions}
              </span>
            </div>
          </div>

          {/* Khu vực bên phải: Trạng thái AI Engine + Số vi phạm + Nút đăng xuất */}
          <div className="flex items-center gap-3 order-2 lg:order-3">
            {/* Huy hiệu trạng thái AI */}
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold border ${
                aiReady
                  ? "bg-green-500/10 text-green-700 border-green-500/30"
                  : "bg-amber-500/10 text-amber-700 border-amber-500/30"
              }`}
            >
              <div
                className={`w-2 h-2 rounded-full ${
                  aiReady
                    ? "bg-green-400 pulse-green"
                    : "bg-amber-400 pulse-red"
                }`}
              />
              <Cpu className="w-3.5 h-3.5" />
              {aiInitError
                ? "Cần kiểm tra camera / AI"
                : aiReady
                  ? "AI hoạt động"
                  : "Đang khởi tạo…"}
            </div>

            {/* Bộ đếm vi phạm */}
            {allViolations.length > 0 && (
              <div
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-red-500/10 text-red-700 
                           border border-red-500/30 text-xs font-semibold"
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                {allViolations.length} vi phạm
              </div>
            )}

            {/* Nút thoát / đăng xuất */}
            <button
              onClick={onLogout}
              className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-500/10 text-slate-700 border border-slate-500/30 hover:bg-slate-500/20 text-xs font-semibold transition-all cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" />
              Thoát / Đổi mã
            </button>
          </div>
        </div>
      </header>

      {/* ═══ BỐ CỤC CHÍNH GRID 12 CỘT (Cột Đề thi 8 cột + Cột Giám sát 4 cột) ═══ */}
      <main className="exam-layout">
        {/* ── CỘT TRÁI: KHU VỰC LÀM BÀI THI (8 CỘT TRÊN XL / 7 CỘT TRÊN LG) ── */}
        <div className="exam-content">
          <div className="exam-stack">
            {/* Thanh tiêu đề bài thi */}
            <div className="glass-card exam-title-card flex items-center justify-between">
              <div>
                <p className="text-sm text-accent-cyan font-semibold tracking-wide uppercase">
                  Mã đề: {examData?.exam_code}
                </p>
                <h1 className="text-2xl font-bold text-text-primary mt-2">
                  {examData?.title}
                </h1>
              </div>
              <div className="text-right hidden sm:block">
                <p className="text-sm text-text-muted">Câu hỏi hiện tại</p>
                <p className="text-3xl font-bold text-accent-cyan">
                  {currentQuestion + 1}
                  <span className="text-lg text-text-muted font-normal">
                    /{totalQuestions}
                  </span>
                </p>
              </div>
            </div>

            {/* Thanh tiến độ bài thi */}
            <div className="w-full h-2 bg-bg-card rounded-full overflow-hidden">
              <motion.div
                className="h-full rounded-full bg-accent-cyan"
                initial={{ width: 0 }}
                animate={{ width: `${progressPercent}%` }}
                transition={{ duration: 0.5, ease: "easeOut" }}
              />
            </div>

            {/* Thẻ nội dung câu hỏi và các phương án lựa chọn */}
            <AnimatePresence mode="wait">
              <motion.div
                key={currentQuestion}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -15 }}
                transition={{ duration: 0.2 }}
                className="glass-card question-card flex-grow"
              >
                {/* Nội dung câu hỏi */}
                <div className="flex gap-4">
                  <span className="flex-shrink-0 w-10 h-10 rounded-xl bg-accent-cyan/15 text-accent-cyan font-bold text-lg flex items-center justify-center">
                    {currentQuestion + 1}
                  </span>
                  <p className="text-xl text-text-primary leading-relaxed pt-1">
                    {question.content}
                  </p>
                </div>

                {/* Danh sách 4 phương án trắc nghiệm */}
                <div className="answer-list">
                  {[
                    ["A", question.option_a],
                    ["B", question.option_b],
                    ["C", question.option_c],
                    ["D", question.option_d],
                  ].map(([letter, text]) => {
                    const isSelected = answers[question.id] === letter;
                    return (
                      <motion.label
                        key={letter}
                        whileHover={{ scale: 1.005 }}
                        whileTap={{ scale: 0.995 }}
                        onClick={() => selectAnswer(question.id, letter)}
                        className={`flex items-center gap-5 p-5 rounded-2xl cursor-pointer transition-all duration-200 border w-full
                          ${
                            isSelected
                              ? "bg-cyan-500/10 border-cyan-500/40 shadow-sm shadow-cyan-500/10"
                              : "bg-bg-card/50 border-border-default hover:bg-bg-card-hover hover:border-text-muted/30"
                          }
                        `}
                      >
                        <input
                          type="radio"
                          name={`q-${question.id}`}
                          checked={isSelected}
                          onChange={() => selectAnswer(question.id, letter)}
                          value={letter}
                          className="w-5 h-5 flex-shrink-0"
                        />
                        <span
                          className={`text-lg leading-relaxed ${
                            isSelected
                              ? "text-text-primary font-medium"
                              : "text-text-secondary"
                          }`}
                        >
                          <span className="font-bold mr-2">{letter}.</span>
                          {text}
                        </span>
                      </motion.label>
                    );
                  })}
                </div>
              </motion.div>
            </AnimatePresence>

            {/* Banner báo lỗi khi nộp bài thất bại (VD: mất kết nối mạng) — cho phép bấm lại nút Nộp bài để thử lại */}
            {submitError && (
              <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
                <AlertTriangle className="w-4 h-4 text-red-700 flex-shrink-0 mt-0.5" />
                <p className="text-red-700 text-sm leading-relaxed">
                  Nộp bài thất bại: {submitError} — bài làm của bạn vẫn được giữ
                  nguyên, hãy thử bấm "Nộp bài thi" lại.
                </p>
              </div>
            )}

            {/* Các nút điều hướng bài thi: Câu trước, Câu tiếp và Nộp bài */}
            <div className="flex items-center justify-between pb-8">
              <button
                onClick={() => goToQuestion(currentQuestion - 1)}
                disabled={currentQuestion === 0}
                className="flex items-center gap-2 px-6 py-3 rounded-xl text-base font-semibold
                           bg-bg-card border border-border-default text-text-secondary
                           hover:bg-bg-card-hover hover:text-text-primary disabled:opacity-30 
                           disabled:cursor-not-allowed transition-all cursor-pointer"
              >
                <ChevronLeft className="w-5 h-5" /> Câu trước
              </button>

              {currentQuestion === totalQuestions - 1 ? (
                <button
                  onClick={() => handleSubmitExam(false)}
                  disabled={submitting}
                  className="flex items-center gap-2 px-8 py-3 rounded-xl text-base font-bold
                             bg-accent-cyan text-white
                             hover:brightness-95 shadow-sm
                             active:scale-[0.98] transition-all cursor-pointer
                             disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {submitting ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" /> Đang nộp
                      bài...
                    </>
                  ) : (
                    <>
                      <Send className="w-5 h-5" /> Nộp bài thi
                    </>
                  )}
                </button>
              ) : (
                <button
                  onClick={() => goToQuestion(currentQuestion + 1)}
                  className="flex items-center gap-2 px-6 py-3 rounded-xl text-base font-semibold
                             bg-accent-cyan/15 text-accent-cyan border border-cyan-500/30
                             hover:bg-accent-cyan/25 transition-all cursor-pointer"
                >
                  Câu tiếp <ChevronRight className="w-5 h-5" />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ── CỘT PHẢI: CAMERA GIÁM SÁT & NHẬT KÝ VI PHẠM (4 CỘT TRÊN XL / 5 CỘT TRÊN LG) ── */}
        <aside className="exam-aside">
          <section className="glass-card question-navigation">
            <h2>
              Danh sách câu hỏi{" "}
              <span>
                {answeredCount}/{totalQuestions}
              </span>
            </h2>
            {/* Danh sách nút chuyển nhanh câu hỏi */}
            <div className="question-grid">
              {examData.questions.map((q, idx) => {
                const isActive = idx === currentQuestion;
                const isAnswered = answers[q.id] !== undefined;
                return (
                  <button
                    key={q.id}
                    onClick={() => goToQuestion(idx)}
                    aria-label={`Câu ${idx + 1}${isAnswered ? ", đã trả lời" : ", chưa trả lời"}`}
                    aria-current={isActive ? "step" : undefined}
                    className={`w-12 h-12 rounded-xl text-base font-bold transition-all duration-200 cursor-pointer border
                      ${
                        isActive
                          ? "bg-accent-cyan text-white border-cyan-400 shadow-sm scale-110"
                          : isAnswered
                            ? "bg-green-500/15 text-green-700 border-green-500/30 hover:bg-green-500/25"
                            : "bg-bg-card text-text-muted border-border-default hover:bg-bg-card-hover hover:text-text-primary"
                      }
                    `}
                  >
                    {idx + 1}
                  </button>
                );
              })}
            </div>

            <div className="question-legend">
              <span>
                <i />
                Chưa trả lời
              </span>
              <span>
                <i />
                Đã trả lời
              </span>
            </div>
          </section>
          {aiInitError && (
            <div className="camera-error" role="alert">
              <CameraOff size={19} />
              <p>{aiInitError}</p>
            </div>
          )}
          {/* Widget Camera giám sát trực tiếp */}
          <div className="glass-card overflow-hidden">
            <div className="p-4 border-b border-border-default flex items-center justify-between bg-bg-secondary/50">
              <div className="flex items-center gap-2">
                <Camera className="w-4 h-4 text-text-muted" />
                <span className="text-sm font-semibold text-text-secondary uppercase tracking-wider">
                  Camera giám sát
                </span>
              </div>
              <div
                className={`w-2.5 h-2.5 rounded-full ${
                  aiReady
                    ? "bg-green-400 pulse-green"
                    : "bg-amber-400 pulse-red"
                }`}
              />
            </div>

            <div className="p-4 bg-bg-primary/50">
              {/* Khung hiển thị Video Camera */}
              <div
                className={`relative rounded-2xl overflow-hidden shadow-2xl ${
                  isViolation
                    ? "camera-border-violation"
                    : "camera-border-normal"
                }`}
              >
                <video
                  ref={liveVideoRef}
                  autoPlay
                  playsInline
                  muted
                  className="w-full aspect-[4/3] object-cover bg-bg-card rounded-2xl"
                />

                {/* Huy hiệu thông báo trạng thái AI nổi trên khung hình camera */}
                <div className="camera-status-position" title={aiInitError || currentStatusConfig.description}>
                  <motion.div
                    key={aiStatus}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.2 }}
                    className={`${currentStatusConfig.bgColor} ${currentStatusConfig.borderColor} border
                      camera-status-badge backdrop-blur-md`}
                  >
                    <currentStatusConfig.icon
                      className={`w-5 h-5 ${currentStatusConfig.color}`}
                    />
                    <div className="flex-1 min-w-0">
                      <p
                        className={`text-sm font-bold ${currentStatusConfig.color} truncate`}
                      >
                        {aiInitError
                          ? "Chưa thể giám sát"
                          : currentStatusConfig.label}
                      </p>

                    </div>
                  </motion.div>
                </div>

                {/* Góc thông báo trạng thái LIVE / ALERT */}
                <div className="absolute top-3 right-3">
                  <div
                    className={`px-3 py-1 rounded-full text-xs font-bold backdrop-blur-sm shadow-md ${
                      isViolation
                        ? "bg-red-500/20 text-red-700 border border-red-500/30"
                        : "bg-green-500/20 text-green-700 border border-green-500/30"
                    }`}
                  >
                    {aiInitError
                      ? "LỖI KẾT NỐI"
                      : !aiReady
                        ? "ĐANG CHỜ"
                        : isViolation
                          ? "CẢNH BÁO"
                          : "TRỰC TIẾP"}
                  </div>
                </div>
              </div>

              {/* Bảng thống kê nhanh thông số AI & Số vi phạm */}
              <div className="grid grid-cols-2 gap-3 mt-4">
                <div className="bg-bg-card rounded-xl p-3 text-center border border-border-default shadow-sm">
                  <p className="text-xs text-text-muted uppercase tracking-wide">
                    Giám sát AI
                  </p>
                  <p className="text-sm font-bold text-text-primary mt-1">
                    {aiInitError
                      ? "Chưa sẵn sàng"
                      : aiReady
                        ? "Sẵn sàng"
                        : "Đang tải..."}
                  </p>
                </div>
                <div className="bg-bg-card rounded-xl p-3 text-center border border-border-default shadow-sm">
                  <p className="text-xs text-text-muted uppercase tracking-wide">
                    Số vi phạm
                  </p>
                  <p
                    className={`text-2xl font-bold mt-1 ${allViolations.length > 0 ? "text-red-700" : "text-green-700"}`}
                  >
                    {allViolations.length}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Cảnh báo vi phạm chuyển tab trình duyệt */}
          {tabSwitchCount > 0 && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-4 flex items-center gap-3 shadow-lg">
              <Monitor className="w-6 h-6 text-red-700 flex-shrink-0" />
              <div>
                <p className="text-sm text-red-700 font-bold">
                  Cảnh báo hệ thống
                </p>
                <p className="text-xs text-red-700/80 mt-1">
                  Đã chuyển tab / mất focus {tabSwitchCount} lần
                </p>
              </div>
            </div>
          )}

          {/* Nhật ký vi phạm thời gian thực (Violation Log Feed) */}
          <div className="glass-card flex-1 flex flex-col overflow-hidden max-h-[800px]">
            <div className="flex items-center justify-between px-5 py-4 border-b border-border-default bg-bg-secondary/50">
              <div className="flex items-center gap-2">
                <CircleDot className="w-4 h-4 text-red-700" />
                <span className="text-sm font-semibold text-text-secondary uppercase tracking-wider">
                  Nhật ký Vi phạm
                </span>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 bg-bg-primary/30">
              {allViolations.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full py-8 text-text-muted">
                  <CheckCircle2 className="w-12 h-12 mb-3 text-green-500/30" />
                  <p className="text-base font-medium">Chưa có vi phạm nào</p>
                  <p className="text-sm mt-1 text-text-muted text-center">
                    {aiInitError
                      ? "Camera / AI chưa sẵn sàng"
                      : aiReady
                        ? "Hệ thống AI đang giám sát"
                        : "Đang khởi tạo giám sát"}
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  <AnimatePresence initial={false}>
                    {allViolations.map((log) => (
                      <motion.div
                        key={log.id}
                        initial={{ opacity: 0, x: 20, height: 0 }}
                        animate={{ opacity: 1, x: 0, height: "auto" }}
                        exit={{ opacity: 0, x: -20, height: 0 }}
                        transition={{ duration: 0.25, ease: "easeOut" }}
                        className="bg-bg-card border border-border-default rounded-xl p-3.5 border-l-4 border-l-red-500/60 shadow-md"
                      >
                        <div className="violation-entry">
                          <div className="violation-entry-heading">
                            <span className="violation-entry-label">{log.label}</span>
                            <span className="violation-entry-time">{log.time}</span>
                          </div>
                          <div className="violation-entry-body">
                            {log.image && (
                              <img src={log.image} alt="Ảnh chụp bằng chứng vi phạm"
                                className="violation-entry-image" />
                            )}
                            <p>{log.message}</p>
                          </div>
                        </div>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              )}
            </div>
          </div>
        </aside>
      </main>
    </div>
  );
}
