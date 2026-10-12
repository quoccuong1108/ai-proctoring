class ViolationRecord {
  final String studentId;
  final String studentName;
  final String violationType;
  final DateTime capturedAt;
  final String? imageBase64;

  const ViolationRecord({
    required this.studentId,
    required this.studentName,
    required this.violationType,
    required this.capturedAt,
    this.imageBase64,
  });

  Map<String, dynamic> toJson() {
    return {
      'student_id': studentId,
      'student_name': studentName,
      'violation_type': violationType,
      'captured_at': capturedAt.toUtc().toIso8601String(),
      'image_base64': imageBase64,
    };
  }
}
