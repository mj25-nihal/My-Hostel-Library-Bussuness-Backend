from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from core.services.revenue_service import (
    HostelRevenueService, LibraryRevenueService, CombinedRevenueService
)

class RevenueSummaryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        mode = request.GET.get('mode', 'combined')  # hostel | library | combined

        if mode == 'hostel':
            data = HostelRevenueService.get_summary(start_date, end_date)
        elif mode == 'library':
            data = LibraryRevenueService.get_summary(start_date, end_date)
        else:
            data = CombinedRevenueService.get_summary(start_date, end_date)

        return Response({"mode": mode, "data": data})
