import { Shield, Check, BookOpen, Camera, Clock } from "lucide-react";
export default function StudentGateway({
  studentId,
  studentName,
  stage,
  children,
}) {
  return (
    <div className="student-gateway">
      <header className="gateway-header">
        <div className="brand">
          <span className="brand-mark">
            <Shield size={23} />
          </span>
          EduShield<span className="brand-ai">AI</span>
        </div>
        <span className="gateway-identity">
          {studentName || "Sinh viên"} <strong>{studentId}</strong>
        </span>
      </header>
      <main className="gateway-main">
        <section className="gateway-intro">
          <p className="eyebrow">KHÔNG GIAN SINH VIÊN</p>
          <h1>
            {stage === 3
              ? "Bạn đã hoàn thành."
              : "Sẵn sàng cho\nkỳ thi của bạn"}
          </h1>
          <p>
            {stage === 3
              ? "Kết quả của bài thi được hiển thị bên cạnh. Bạn có thể đăng xuất để kết thúc phiên."
              : "Kiểm tra thông tin, chuẩn bị không gian yên tĩnh và tập trung thể hiện kiến thức của mình."}
          </p>
          <ol className="gateway-steps">
            {["Chọn môn & Đề", "Duyệt & Bắt đầu", "Hoàn thành bài thi"].map(
              (label, i) => (
                <li
                  key={label}
                  className={
                    stage === i + 1
                      ? "current"
                      : stage > i + 1
                        ? "complete"
                        : ""
                  }
                  aria-current={stage === i + 1 ? "step" : undefined}
                >
                  <span>
                    {stage > i + 1 ? <Check size={17} /> : `0${i + 1}`}
                  </span>
                  <strong>{label}</strong>
                </li>
              ),
            )}
          </ol>
          <div className="gateway-tips">
            <span>
              <BookOpen size={17} /> Chọn môn học và đề thi có sẵn
            </span>
            <span>
              <Camera size={17} /> Cho phép camera khi bắt đầu
            </span>
            <span>
              <Clock size={17} /> Theo dõi thời gian trong phòng thi
            </span>
          </div>
        </section>
        <section className="gateway-panel">{children}</section>
      </main>
      <footer className="gateway-footer">
        EduShield AI · Đồng hành cùng mỗi kỳ thi
      </footer>
    </div>
  );
}
