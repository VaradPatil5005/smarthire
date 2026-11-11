from django.urls import path

from apps.ingestion import api as ingestion
from apps.matching import api as matching
from apps.onboarding import api as onboarding
from apps.projects import api as projects
from apps.reports import api as reports
from apps.talent import api as talent

urlpatterns = [
    path("skills/", matching.SkillListView.as_view()),
    path("profiles/me/", talent.MeView.as_view()),
    path("profiles/me/claims/", talent.MeClaimsView.as_view()),
    path("profiles/me/data-requests/", talent.MeDataRequestView.as_view()),
    path("profiles/me/resumes/", ingestion.MeResumesView.as_view()),
    path("profiles/", talent.ProfileListView.as_view()),
    path("profiles/<uuid:pk>/", talent.ProfileDetailView.as_view()),
    path("profiles/<uuid:pk>/resumes/", ingestion.ProfileResumesView.as_view()),
    path("profiles/<uuid:pk>/evidence/", matching.ProfileReviewsView.as_view()),
    path("resumes/<uuid:pk>/", ingestion.ResumeDetailView.as_view()),
    path("resumes/<uuid:pk>/download/", ingestion.ResumeDownloadView.as_view()),
    path("resumes/<uuid:pk>/xray/", ingestion.ResumeXrayView.as_view()),
    path("resumes/<uuid:pk>/pages/<int:page>/", ingestion.ResumePageImageView.as_view()),
    path("projects/", projects.ProjectListView.as_view()),
    path("projects/<uuid:pk>/", projects.ProjectDetailView.as_view()),
    path("projects/<uuid:pk>/close/", projects.ProjectCloseView.as_view()),
    path("projects/<uuid:pk>/rubrics/", projects.RubricListView.as_view()),
    path("projects/<uuid:pk>/rubrics/<int:version>/", projects.RubricDetailView.as_view()),
    path("projects/<uuid:pk>/rubrics/<int:version>/skills/", projects.RubricSkillsView.as_view()),
    path(
        "projects/<uuid:pk>/rubrics/<int:version>/skills/<int:item_id>/",
        projects.RubricSkillDetailView.as_view(),
    ),
    path("projects/<uuid:pk>/rubrics/<int:version>/approve/", projects.RubricApproveView.as_view()),
    path("projects/<uuid:pk>/runs/", matching.ProjectRunsView.as_view()),
    path("runs/<uuid:pk>/", matching.RunDetailView.as_view()),
    path("runs/<uuid:pk>/results/", matching.RunResultsView.as_view()),
    path("runs/<uuid:pk>/reproduce/", matching.RunReproduceView.as_view()),
    path("runs/<uuid:pk>/dashboard/", reports.RunDashboardView.as_view()),
    path("runs/<uuid:pk>/export.csv", reports.RunExportCsvView.as_view()),
    path("runs/<uuid:pk>/export.xlsx", reports.RunExportXlsxView.as_view()),
    path("results/<uuid:pk>/reviews/", matching.ResultReviewsView.as_view()),
    path("reports/utilisation/", reports.UtilisationView.as_view()),
    path("imports/", onboarding.ImportListView.as_view()),
    path("imports/queue/", onboarding.ImportQueueView.as_view()),
    path("imports/queue/<uuid:pk>/resolve/", onboarding.ImportQueueResolveView.as_view()),
    path("imports/<uuid:pk>/", onboarding.ImportDetailView.as_view()),
    path("imports/<uuid:pk>/confirm/", onboarding.ImportConfirmView.as_view()),
    path("imports/<uuid:pk>/rollback/", onboarding.ImportRollbackView.as_view()),
]
