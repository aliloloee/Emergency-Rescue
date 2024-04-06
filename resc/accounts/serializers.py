from rest_framework import serializers
from django.contrib.auth import get_user_model


User = get_user_model()


class RegisterUserSerializer(serializers.ModelSerializer):

    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        ref_name = None
        model = User
        fields = ('email', 'firstname', 'lastname', 'password', 'confirm_password', )

        extra_kwargs = {
            'password': {
                'write_only' : True,
                'style' : {'input_type' : 'password'},
            },
            'confirm_password': {
                'write_only' : True,
                'style' : {'input_type' : 'password'},
            }
        }

    def validate(self, data) :
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError(_("Passwords do not match"))
        return data

    def create(self, validated_data):
        validated_data.pop('confirm_password', None)
        instance = super().create(validated_data)
        instance.save()
        return instance