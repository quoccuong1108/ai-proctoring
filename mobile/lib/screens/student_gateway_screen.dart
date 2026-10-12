import 'package:flutter/material.dart';

class StudentGatewayScreen extends StatefulWidget {
  final String studentId;
  final String studentName;
  final String examCode;
  final ValueChanged<String> onStudentIdChanged;
  final ValueChanged<String> onStudentNameChanged;
  final ValueChanged<String> onExamCodeChanged;
  final Future<void> Function() onContinue;
  final bool isLoading;
  final String? errorMessage;

  const StudentGatewayScreen({
    super.key,
    required this.studentId,
    required this.studentName,
    required this.examCode,
    required this.onStudentIdChanged,
    required this.onStudentNameChanged,
    required this.onExamCodeChanged,
    required this.onContinue,
    required this.isLoading,
    this.errorMessage,
  });

  @override
  State<StudentGatewayScreen> createState() => _StudentGatewayScreenState();
}

class _StudentGatewayScreenState extends State<StudentGatewayScreen> {
  final _formKey = GlobalKey<FormState>();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF8FAFC),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: Card(
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Form(
                      key: _formKey,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            children: const [
                              Icon(Icons.shield, color: Color(0xFF2563EB), size: 28),
                              SizedBox(width: 10),
                              Text(
                                'EduShield AI',
                                style: TextStyle(
                                  fontSize: 28,
                                  fontWeight: FontWeight.bold,
                                  color: Color(0xFF0F172A),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 28),
                          const Text(
                            'Mở phiên thi',
                            style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold),
                          ),
                          const SizedBox(height: 8),
                          const Text(
                            'Nhập thông tin sinh viên và mã đề để bắt đầu phòng thi.',
                            style: TextStyle(color: Colors.black54),
                          ),
                          const SizedBox(height: 22),
                          TextFormField(
                            initialValue: widget.studentId,
                            decoration: const InputDecoration(
                              labelText: 'Mã sinh viên',
                              prefixIcon: Icon(Icons.badge_outlined),
                              border: OutlineInputBorder(),
                            ),
                            onChanged: widget.onStudentIdChanged,
                            validator: (value) =>
                                (value == null || value.trim().isEmpty) ? 'Vui lòng nhập mã sinh viên' : null,
                          ),
                          const SizedBox(height: 18),
                          TextFormField(
                            initialValue: widget.studentName,
                            decoration: const InputDecoration(
                              labelText: 'Họ và tên',
                              prefixIcon: Icon(Icons.person_outline),
                              border: OutlineInputBorder(),
                            ),
                            onChanged: widget.onStudentNameChanged,
                            validator: (value) =>
                                (value == null || value.trim().isEmpty) ? 'Vui lòng nhập họ và tên' : null,
                          ),
                          const SizedBox(height: 18),
                          TextFormField(
                            initialValue: widget.examCode,
                            decoration: const InputDecoration(
                              labelText: 'Mã đề thi',
                              prefixIcon: Icon(Icons.bookmark_outline),
                              border: OutlineInputBorder(),
                            ),
                            onChanged: widget.onExamCodeChanged,
                            validator: (value) =>
                                (value == null || value.trim().isEmpty) ? 'Vui lòng nhập mã đề' : null,
                          ),
                          if (widget.errorMessage != null && widget.errorMessage!.isNotEmpty) ...[
                            const SizedBox(height: 14),
                            Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: Colors.red.shade50,
                                borderRadius: BorderRadius.circular(12),
                                border: Border.all(color: Colors.red.shade200),
                              ),
                              child: Text(
                                widget.errorMessage!,
                                style: const TextStyle(color: Colors.red),
                              ),
                            ),
                          ],
                          const SizedBox(height: 28),
                          FilledButton.icon(
                            onPressed: widget.isLoading
                                ? null
                                : () {
                                    if (_formKey.currentState!.validate()) {
                                      widget.onContinue();
                                    }
                                  },
                            icon: widget.isLoading
                                ? const SizedBox(
                                    width: 18,
                                    height: 18,
                                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                                  )
                                : const Icon(Icons.arrow_forward_rounded),
                            label: Text(widget.isLoading ? 'Đang kiểm tra...' : 'Tiếp tục'),
                            style: FilledButton.styleFrom(
                              minimumSize: const Size.fromHeight(52),
                              backgroundColor: const Color(0xFF2563EB),
                              foregroundColor: Colors.white,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
