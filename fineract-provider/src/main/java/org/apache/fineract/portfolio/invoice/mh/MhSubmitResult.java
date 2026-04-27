package org.apache.fineract.portfolio.invoice.mh;

public final class MhSubmitResult {

    private final boolean success;
    private final String jobId;
    private final String errorMessage;

    private MhSubmitResult(boolean success, String jobId, String errorMessage) {
        this.success = success;
        this.jobId = jobId;
        this.errorMessage = errorMessage;
    }

    public static MhSubmitResult accepted(String jobId) {
        return new MhSubmitResult(true, jobId, null);
    }

    public static MhSubmitResult syncOk(String bodyNote) {
        return new MhSubmitResult(true, null, bodyNote);
    }

    public static MhSubmitResult error(String message) {
        return new MhSubmitResult(false, null, message);
    }

    public boolean isSuccess() {
        return success;
    }

    public String getJobId() {
        return jobId;
    }

    public String getErrorMessage() {
        return errorMessage;
    }
}
