import 'package:flutter/material.dart';

class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 96,
              height: 96,
              decoration: BoxDecoration(
                color: Colors.white.withAlpha(31),
                borderRadius: BorderRadius.circular(28),
              ),
              child: const Icon(
                Icons.shield_outlined,
                size: 52,
                color: Colors.white,
              ),
            ),
            const SizedBox(height: 24),
            const Text(
              'EduShield AI',
              style: TextStyle(
                color: Colors.white,
                fontSize: 36,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              'AI Proctoring for online exams',
              style: TextStyle(
                color: Colors.white70,
                fontSize: 16,
              ),
            ),
            const SizedBox(height: 28),
            const CircularProgressIndicator(color: Colors.white),
          ],
        ),
      ),
    );
  }
}
