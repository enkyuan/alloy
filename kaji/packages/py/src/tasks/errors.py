"""Task projection errors."""


class TaskError(RuntimeError):
    pass


class TaskNotFoundError(TaskError):
    pass


class InvalidTaskTransitionError(TaskError):
    pass


class TaskProjectionError(TaskError):
    pass
