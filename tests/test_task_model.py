import unittest

from backend.models.task import Task


class TaskModelTests(unittest.TestCase):
    def test_update_progress_ignores_skip_count(self):
        task = Task(total_count=10, success_count=3, failed_count=1, skip_count=20)
        task.update_progress()

        self.assertEqual(task.progress, 40.0)


if __name__ == "__main__":
    unittest.main()
