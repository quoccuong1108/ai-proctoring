class ExamQuestion {
  final int id;
  final int orderIndex;
  final String content;
  final String optionA;
  final String optionB;
  final String optionC;
  final String optionD;
  final String? correctOption;

  const ExamQuestion({
    required this.id,
    required this.orderIndex,
    required this.content,
    required this.optionA,
    required this.optionB,
    required this.optionC,
    required this.optionD,
    this.correctOption,
  });

  factory ExamQuestion.fromJson(Map<String, dynamic> json) {
    return ExamQuestion(
      id: (json['id'] as num?)?.toInt() ?? 0,
      orderIndex: (json['order_index'] as num?)?.toInt() ?? 0,
      content: (json['content'] ?? '').toString(),
      optionA: (json['option_a'] ?? '').toString(),
      optionB: (json['option_b'] ?? '').toString(),
      optionC: (json['option_c'] ?? '').toString(),
      optionD: (json['option_d'] ?? '').toString(),
      correctOption: json['correct_option']?.toString(),
    );
  }

  List<String> get options => [optionA, optionB, optionC, optionD];
}

class Exam {
  final int id;
  final String examCode;
  final String title;
  final int durationMinutes;
  final List<ExamQuestion> questions;

  const Exam({
    required this.id,
    required this.examCode,
    required this.title,
    required this.durationMinutes,
    required this.questions,
  });

  factory Exam.fromJson(Map<String, dynamic> json) {
    final rawQuestions = (json['questions'] as List<dynamic>? ?? const <dynamic>[]);
    return Exam(
      id: (json['exam_id'] ?? json['id'] as num?)?.toInt() ?? 0,
      examCode: (json['exam_code'] ?? '').toString(),
      title: (json['title'] ?? '').toString(),
      durationMinutes: (json['duration_minutes'] as num?)?.toInt() ?? 0,
      questions: rawQuestions
          .map((e) => ExamQuestion.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList(),
    );
  }
}
