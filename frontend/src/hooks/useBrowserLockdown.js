import { useEffect, useRef, useState, useCallback } from 'react';

/**
 * useBrowserLockdown - Custom Hook cho chế độ khóa trình duyệt khi thi
 *
 * Chức năng:
 *   1. Ép Fullscreen + hiện overlay bắt buộc nếu thoát
 *   2. Phát hiện chuyển tab / thu nhỏ cửa sổ
 *   3. Chặn phím tắt gian lận (F12, Ctrl+C/V/X/U, Ctrl+Shift+I/J/C)
 *   4. Chặn chuột phải, copy, paste, cut
 *
 * @param {{ onViolation?: (type: string, message: string) => void }} [options]
 *   onViolation: được gọi mỗi khi ghi nhận một vi phạm lockdown — nơi gọi dùng để gửi lên server.
 *
 * @returns {{
 *   isFullscreen: boolean,
 *   tabSwitchCount: number,
 *   showFullscreenOverlay: boolean,
 *   requestFullscreen: () => void,
 *   violations: Array<{type: string, timestamp: string, message: string}>
 * }}
 */
export default function useBrowserLockdown({ onViolation } = {}) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showFullscreenOverlay, setShowFullscreenOverlay] = useState(false);
  const [showBlurOverlay, setShowBlurOverlay] = useState(false);
  const [tabSwitchCount, setTabSwitchCount] = useState(0);
  const [violations, setViolations] = useState([]);

  const tabSwitchCountRef = useRef(0);
  const isInitializedRef = useRef(false);
  // Thời điểm lần "rời cửa sổ" gần nhất đã được đếm — trên điện thoại một lần chuyển app
  // có thể bắn cả visibilitychange lẫn blur, không được đếm thành 2 vi phạm.
  const lastLeaveAtRef = useRef(0);
  // Giữ callback mới nhất trong ref để không phải đăng ký lại toàn bộ listener khi nó đổi
  const onViolationRef = useRef(onViolation);
  useEffect(() => {
    onViolationRef.current = onViolation;
  }, [onViolation]);

  /**
   * Ghi nhận một vi phạm lockdown mới
   */
  const addViolation = useCallback((type, message) => {
    const entry = {
      id: Date.now() + Math.random(),
      type,
      timestamp: new Date().toLocaleTimeString('vi-VN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
      message,
    };
    setViolations((prev) => [entry, ...prev]);
    try {
      onViolationRef.current?.(type, message);
    } catch (err) {
      console.warn('onViolation callback lỗi:', err);
    }
  }, []);

  /**
   * Yêu cầu vào chế độ Fullscreen
   */
  const requestFullscreen = useCallback(() => {
    const el = document.documentElement;
    try {
      if (el.requestFullscreen) {
        el.requestFullscreen().catch(() => {});
      } else if (el.webkitRequestFullscreen) {
        el.webkitRequestFullscreen();
      } else if (el.msRequestFullscreen) {
        el.msRequestFullscreen();
      }
    } catch (err) {
      console.warn('Fullscreen request failed:', err);
    }
  }, []);

  useEffect(() => {
    // ──────────────────────────────────────────────────
    // 1. FULLSCREEN ENFORCEMENT
    // ──────────────────────────────────────────────────
    const handleFullscreenChange = () => {
      const isFull = Boolean(
        document.fullscreenElement ||
        document.webkitFullscreenElement ||
        document.msFullscreenElement
      );
      setIsFullscreen(isFull);

      if (!isFull) {
        setShowFullscreenOverlay(true);
        addViolation('FULLSCREEN_EXIT', 'Thoát chế độ toàn màn hình');
      } else {
        setShowFullscreenOverlay(false);
      }
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    document.addEventListener('webkitfullscreenchange', handleFullscreenChange);

    // ──────────────────────────────────────────────────
    // 2. TAB SWITCH / WINDOW BLUR DETECTION
    // ──────────────────────────────────────────────────
    const handleVisibilityChange = () => {
      if (document.hidden) {
        const now = Date.now();
        if (now - lastLeaveAtRef.current < 1500) return; // đã đếm lần rời này rồi
        lastLeaveAtRef.current = now;
        tabSwitchCountRef.current += 1;
        setTabSwitchCount(tabSwitchCountRef.current);
        setShowBlurOverlay(true);
        addViolation('TAB_SWITCH', `Chuyển tab / thu nhỏ cửa sổ (Lần ${tabSwitchCountRef.current})`);
      }
    };

    const handleWindowBlur = () => {
      // Bổ sung bắt sự kiện blur khi click ra ngoài cửa sổ
      if (!document.hidden) {
        const now = Date.now();
        if (now - lastLeaveAtRef.current < 1500) return; // visibilitychange vừa đếm lần rời này
        lastLeaveAtRef.current = now;
        tabSwitchCountRef.current += 1;
        setTabSwitchCount(tabSwitchCountRef.current);
        setShowBlurOverlay(true);
        addViolation('WINDOW_BLUR', `Mất focus cửa sổ thi (Lần ${tabSwitchCountRef.current})`);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('blur', handleWindowBlur);

    // ──────────────────────────────────────────────────
    // 3. KEYBOARD SHORTCUT BLOCKING
    // ──────────────────────────────────────────────────
    const blockedKeys = new Set([
      'F12',
      'F5',
    ]);

    const blockedCtrlKeys = new Set([
      'c', 'v', 'x', 'u', 'a', 's', 'p',
    ]);

    const blockedCtrlShiftKeys = new Set([
      'i', 'j', 'c',
    ]);

    const handleKeyDown = (e) => {
      // Block F12, F5
      if (blockedKeys.has(e.key)) {
        e.preventDefault();
        e.stopPropagation();
        addViolation('BLOCKED_KEY', `Phím ${e.key} bị chặn`);
        return;
      }

      // Block Ctrl + key
      if (e.ctrlKey && !e.shiftKey && blockedCtrlKeys.has(e.key.toLowerCase())) {
        e.preventDefault();
        e.stopPropagation();
        addViolation('BLOCKED_KEY', `Tổ hợp Ctrl+${e.key.toUpperCase()} bị chặn`);
        return;
      }

      // Block Ctrl+Shift + key (DevTools)
      if (e.ctrlKey && e.shiftKey && blockedCtrlShiftKeys.has(e.key.toLowerCase())) {
        e.preventDefault();
        e.stopPropagation();
        addViolation('BLOCKED_KEY', `Tổ hợp Ctrl+Shift+${e.key.toUpperCase()} bị chặn`);
        return;
      }

      // Block Alt+Tab indicator (browser may not fully block this)
      if (e.altKey && e.key === 'Tab') {
        e.preventDefault();
        e.stopPropagation();
        return;
      }
    };

    document.addEventListener('keydown', handleKeyDown, { capture: true });

    // ──────────────────────────────────────────────────
    // 4. CONTEXT MENU / COPY / PASTE / CUT BLOCKING
    // ──────────────────────────────────────────────────
    const handleContextMenu = (e) => {
      e.preventDefault();
      addViolation('RIGHT_CLICK', 'Click chuột phải bị chặn');
    };

    const handleCopy = (e) => {
      e.preventDefault();
      addViolation('COPY_ATTEMPT', 'Hành vi sao chép (Copy) bị chặn');
    };

    const handlePaste = (e) => {
      e.preventDefault();
      addViolation('PASTE_ATTEMPT', 'Hành vi dán (Paste) bị chặn');
    };

    const handleCut = (e) => {
      e.preventDefault();
      addViolation('CUT_ATTEMPT', 'Hành vi cắt (Cut) bị chặn');
    };

    document.addEventListener('contextmenu', handleContextMenu);
    document.addEventListener('copy', handleCopy);
    document.addEventListener('paste', handlePaste);
    document.addEventListener('cut', handleCut);

    // ──────────────────────────────────────────────────
    // CLEANUP
    // ──────────────────────────────────────────────────
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      document.removeEventListener('webkitfullscreenchange', handleFullscreenChange);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('blur', handleWindowBlur);
      document.removeEventListener('keydown', handleKeyDown, { capture: true });
      document.removeEventListener('contextmenu', handleContextMenu);
      document.removeEventListener('copy', handleCopy);
      document.removeEventListener('paste', handlePaste);
      document.removeEventListener('cut', handleCut);
    };
  }, [addViolation]);

  const dismissBlurOverlay = useCallback(() => setShowBlurOverlay(false), []);

  return {
    isFullscreen,
    showFullscreenOverlay,
    showBlurOverlay,
    tabSwitchCount,
    violations,
    requestFullscreen,
    dismissBlurOverlay,
  };
}
