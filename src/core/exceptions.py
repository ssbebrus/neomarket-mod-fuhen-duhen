from fastapi import HTTPException, status

class NotFoundException(HTTPException):
    def __init__(self, detail: str = "Item not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class BlockingReasonAlreadyExists(Exception):
    pass


class BlockingReasonNotFound(Exception):
    pass


class DuplicateCreatedEvent(Exception):
    pass


class TicketNotFound(Exception):
    pass


class B2BIntegrationError(Exception):
    pass


class InvalidServiceKey(Exception):
    pass


class ModeratorAlreadyHasActiveTicket(Exception):
    pass


class TicketWrongStatus(Exception):
    def __init__(self, message: str = "Wrong ticket status"):
        self.message = message
        super().__init__(message)


class NotAssignedModerator(Exception):
    pass


class ProductHasNoSKUs(Exception):
    pass


class InvalidFieldReport(Exception):
    def __init__(self, message: str = "Invalid field report"):
        self.message = message
        super().__init__(message)


class HardBlockReasonNotAllowed(Exception):
    pass




