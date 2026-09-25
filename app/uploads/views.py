from django.shortcuts import redirect, render

from .forms import DocumentoForm
from .models import Documento


def lista_documentos(request):
    if request.method == 'POST':
        form = DocumentoForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('lista_documentos')
    else:
        form = DocumentoForm()

    return render(request, 'uploads/lista.html', {
        'form': form,
        'documentos': Documento.objects.all(),
    })
