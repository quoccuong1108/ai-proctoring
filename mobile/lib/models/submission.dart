class SubmitAnswer {
  final int questionId;
  final String selectedOption;

  const SubmitAnswer({required this.questionId, required this.selectedOption});

  Map<String, dynamic> toJson() {
    return {
      'question_id': questionId,
      'selected_option': selectedOption,
    };
  }
}

class SubmitExamRequest {
  final String studentId;
  final String studentName;
  final List<SubmitAnswer> answers;
  final bool autoSubmitted;

  const SubmitExamRequest({
    required this.studentId,
    required this.studentName,
    required this.answers,
    required this.autoSubmitted,
  });

  Map<String, dynamic> toJson() {
    return {
      'student_id': studentId,
      'student_name': studentName,
      'answers': answers.map((e) => e.toJson()).toList(),
      'auto_submitted': autoSubmitted,
    };
  }
}

class ExamResult {
  final double totalScore;
  final int correctCount;
  final int totalQuestions;
  final double passScore;
  final bool passed;
  final String status;

  const ExamResult({
    required this.totalScore,
    required this.correctCount,
    required this.totalQuestions,
    required this.passScore,
    required this.passed,
    required this.status,
  });

  factory ExamResult.fromJson(Map<String, dynamic> json) {
    return ExamResult(
      totalScore: (json['total_score'] as num?)?.toDouble() ?? 0,
      correctCount: (json['correct_count'] as num?)?.toInt() ?? 0,
      totalQuestions: (json['total_questions'] as num?)?.toInt() ?? 0,
      passScore: (json['pass_score'] as num?)?.toDouble() ?? 0,
      passed: json['passed'] as bool? ?? false,
      status: (json['status'] ?? '').toString(),
    );
  }
}
