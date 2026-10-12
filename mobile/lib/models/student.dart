class StudentProfile {
  final String studentId;
  final String name;

  const StudentProfile({required this.studentId, required this.name});

  factory StudentProfile.empty() => const StudentProfile(studentId: '', name: '');

  StudentProfile copyWith({String? studentId, String? name}) {
    return StudentProfile(
      studentId: studentId ?? this.studentId,
      name: name ?? this.name,
    );
  }
}
